"""
Vector memory store.

Embeddings: Voyage AI voyage-3 (1024 dimensions) via httpx
Storage:    Supabase pgvector
Extraction: Claude Haiku decides what's worth saving
"""
import os
import json
import asyncio
from datetime import datetime, timezone
import httpx
from supabase import create_client, Client

_client: Client | None = None

_VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
_VOYAGE_MODEL = "voyage-3"

_SHOULD_REMEMBER_PROMPT_BASE = (
    "Does this conversation exchange contain anything worth a companion remembering long-term? "
    "Look for: facts about the user (name, job, family, pets, location), "
    "preferences (likes/dislikes, hobbies), emotional moments (confessions, vulnerable shares, breakthroughs), "
    "relationship milestones, or recurring themes.\n\n"
    "If yes, return JSON:\n"
    '{"should_save": true, '
    '"content": "concise memory in 1-2 sentences written from companion POV, '
    'e.g. The user told me their dog is named Biscuit", '
    '"type": "fact|emotion|preference|event|relationship", '
    '"importance": 1-10, '
    '"person_mentioned": "first name of person this memory is about, or null if about the user themselves", '
    '"emotional_theme": "one of: joy|grief|growth|conflict|love|pride|fear|hope|loneliness|gratitude — or null", '
    '"life_event": true or false (true only for significant milestones: births, deaths, marriages, divorces, moves, diagnoses, major career changes), '
    '"topic": "one of: relationship|career|family|health|personal_growth|friendship|loss|identity|spirituality — or null"}\n\n'
    'If nothing worth saving, return {"should_save": false}.\n'
    "Return ONLY valid JSON, no other text."
)


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _client = create_client(url, key)
    return _client


async def embed(text: str) -> list[float]:
    """Generate a voyage-3 embedding (1024 dims) for the given text."""
    api_key = os.environ.get("VOYAGE_API_KEY", "")
    if not api_key:
        raise RuntimeError("VOYAGE_API_KEY must be set")
    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.post(
            _VOYAGE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": _VOYAGE_MODEL, "input": [text]},
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


async def should_remember(user_msg: str, companion_msg: str) -> dict | None:
    """
    Use Claude Haiku to decide if this exchange contains something worth saving.
    Returns parsed dict with {content, type, importance} or None.
    """
    from app import claude  # late import — avoids circular at module level
    prompt = _SHOULD_REMEMBER_PROMPT_BASE
    try:
        turn = f"User: {user_msg}\nCompanion: {companion_msg}"
        raw = await claude.send_message(
            system_prompt=prompt,
            history=[],
            user_message=turn,
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
        )
        # Strip markdown code fences if Claude wraps the JSON
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        result = json.loads(cleaned)
        if not result.get("should_save"):
            print(f"[memory] should_remember: not worth saving for exchange: {turn[:80]!r}")
            return None
        print(f"[memory] should_remember: SAVING — type={result.get('type')} importance={result.get('importance')} content={result.get('content','')[:80]!r}")
        return result
    except Exception as exc:
        raw_preview = repr(raw) if "raw" in dir() else "n/a"
        print(f"[memory] should_remember ERROR: {exc!r} | raw response: {raw_preview}")
        return None


async def save_memory(
    user_id: str,
    companion_id: str,
    content: str,
    memory_type: str = "fact",
    importance: int = 5,
    # Legacy Mode tagging fields — stored silently, power future features
    person_mentioned: str | None = None,
    emotional_theme: str | None = None,
    life_event: bool = False,
    topic: str | None = None,
) -> dict:
    """
    Embed content and POST directly to /rest/v1/memories via httpx.
    Using raw httpx (not supabase-py) gives full transparency and avoids
    any client-side caching layers. Returns {} silently on any error.

    Legacy tagging fields (person_mentioned, emotional_theme, life_event, topic)
    are stored alongside the embedding to power Legacy Mode when it unlocks.
    Run these SQL migrations to enable them:
      ALTER TABLE memories ADD COLUMN IF NOT EXISTS person_mentioned text;
      ALTER TABLE memories ADD COLUMN IF NOT EXISTS emotional_theme   text;
      ALTER TABLE memories ADD COLUMN IF NOT EXISTS life_event        boolean DEFAULT false;
      ALTER TABLE memories ADD COLUMN IF NOT EXISTS topic             text;
    """
    print(f"[memory] save_memory: user={user_id} companion={companion_id} type={memory_type} importance={importance} content={content[:80]!r}")
    try:
        embedding = await embed(content)
        # PostgreSQL vector literal expected by pgvector: "[x,y,z,...]"
        vec_str = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"

        supabase_url = os.environ.get("SUPABASE_URL", "")
        service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")

        payload: dict = {
            "user_id": user_id,
            "companion_id": companion_id,
            "content": content,
            "memory_type": memory_type,
            "embedding": vec_str,
            "importance": max(1, min(10, int(importance))),
        }
        # Add legacy tags only when present — columns may not exist yet in older schemas
        if person_mentioned:
            payload["person_mentioned"] = person_mentioned
        if emotional_theme:
            payload["emotional_theme"] = emotional_theme
        if life_event:
            payload["life_event"] = True
        if topic:
            payload["topic"] = topic

        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                f"{supabase_url}/rest/v1/memories",
                headers={
                    "Authorization": f"Bearer {service_key}",
                    "apikey": service_key,
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
                json=payload,
            )
            if resp.status_code in (200, 201):
                rows = resp.json()
                print(f"[memory] save_memory: OK — row saved, id={rows[0].get('id') if rows else 'n/a'}")
                return rows[0] if rows else {}
            print(f"[memory] save_memory ERROR: HTTP {resp.status_code} — {resp.text[:300]}")
            return {}
    except Exception as exc:
        print(f"[memory] save_memory EXCEPTION: {exc!r}")
        return {}


async def retrieve_memories(
    user_id: str,
    companion_id: str,
    query_text: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Find the top_k most semantically similar memories via cosine similarity,
    then rerank using a composite salience formula:

        final_score = (0.50 * cosine_similarity)
                    + (0.25 * emotional_intensity)
                    + (0.15 * recurrence_signal)
                    + (0.10 * recency_weight)

    Results are re-sorted by final_score descending before returning.
    retrieval_count and last_retrieved are updated fire-and-forget.
    Returns [] on any error.
    """
    try:
        query_embedding = await embed(query_text)
        client = _get_client()
        result = client.rpc("match_memories", {
            "query_embedding": query_embedding,
            "match_user_id": user_id,
            "match_companion_id": companion_id,
            "match_count": top_k,
        }).execute()
        memories: list[dict] = result.data or []
        print(f"[memory] retrieve_memories: user={user_id} companion={companion_id} found={len(memories)} memories")

        if not memories:
            return memories

        # ── Fetch salience + retrieval fields for reranking ───────────────
        ids = [m["id"] for m in memories if m.get("id")]
        extra = await _fetch_salience_fields(ids)

        # ── Reranking formula ─────────────────────────────────────────────
        now_utc = datetime.now(timezone.utc)
        for m in memories:
            mid = m.get("id", "")
            ex = extra.get(mid, {})

            cosine_sim = float(m.get("similarity", 0.0))

            sal = ex.get("salience") or {}
            if isinstance(sal, str):
                try:
                    sal = json.loads(sal)
                except Exception:
                    sal = {}
            emotional_intensity = max(0.0, min(1.0, float(sal.get("emotional_intensity", 0.5))))

            retrieval_count = int(ex.get("retrieval_count") or 0)
            recurrence_signal = min(retrieval_count / 10.0, 1.0)

            last_retrieved_raw = ex.get("last_retrieved")
            if last_retrieved_raw:
                try:
                    lr = datetime.fromisoformat(last_retrieved_raw.replace("Z", "+00:00"))
                    delta_days = (now_utc - lr).days
                    recency_weight = 1.0 if delta_days <= 7 else (0.5 if delta_days <= 30 else 0.0)
                except Exception:
                    recency_weight = 0.0
            else:
                recency_weight = 0.0

            m["final_score"] = (
                0.50 * cosine_sim
                + 0.25 * emotional_intensity
                + 0.15 * recurrence_signal
                + 0.10 * recency_weight
            )

        memories.sort(key=lambda m: m.get("final_score", 0.0), reverse=True)

        # ── Update retrieval stats fire-and-forget ────────────────────────
        if ids:
            asyncio.create_task(_update_retrieval_stats(ids, extra))

        return memories

    except Exception as exc:
        print(f"[memory] retrieve_memories EXCEPTION: {exc!r}")
        return []


async def _fetch_salience_fields(ids: list[str]) -> dict[str, dict]:
    """
    Batch-fetch salience, retrieval_count, last_retrieved for a list of memory IDs.
    Returns a dict keyed by id. Returns {} on any error (reranking falls back to defaults).
    """
    if not ids:
        return {}
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    ids_param = "(" + ",".join(ids) + ")"
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            resp = await http.get(
                f"{supabase_url}/rest/v1/memories",
                headers={"Authorization": f"Bearer {service_key}", "apikey": service_key},
                params={
                    "id": f"in.{ids_param}",
                    "select": "id,salience,retrieval_count,last_retrieved",
                },
            )
        if resp.status_code == 200:
            return {row["id"]: row for row in resp.json()}
        print(f"[memory] _fetch_salience_fields HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        print(f"[memory] _fetch_salience_fields EXCEPTION: {exc!r}")
    return {}


async def _update_retrieval_stats(ids: list[str], extra: dict[str, dict]) -> None:
    """
    Increment retrieval_count and set last_retrieved = now() for each memory.
    Uses current counts from `extra` to compute the new value without a race-prone RPC.
    Fire-and-forget — errors are logged and never propagate.
    """
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    now_iso = datetime.now(timezone.utc).isoformat()
    headers = {
        "Authorization": f"Bearer {service_key}",
        "apikey": service_key,
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    async with httpx.AsyncClient(timeout=10.0) as http:
        for mid in ids:
            current_count = int((extra.get(mid) or {}).get("retrieval_count") or 0)
            try:
                await http.patch(
                    f"{supabase_url}/rest/v1/memories",
                    headers=headers,
                    params={"id": f"eq.{mid}"},
                    json={"retrieval_count": current_count + 1, "last_retrieved": now_iso},
                )
            except Exception as exc:
                print(f"[memory] _update_retrieval_stats EXCEPTION id={mid}: {exc!r}")


async def fetch_memories(user_id: str, persona_id: str, limit: int = 10) -> list[dict]:
    """
    Fetch recent memories by creation time (used by GET /api/memories and legacy paths).
    Accepts persona_id as alias for companion_id — same values.
    """
    try:
        client = _get_client()
        result = (
            client.table("memories")
            .select("id, content, memory_type, importance, created_at")
            .eq("user_id", user_id)
            .eq("companion_id", persona_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


async def list_all_memories(user_id: str, persona_id: str) -> list[dict]:
    """Return all memories for the GET /api/memories endpoint."""
    try:
        client = _get_client()
        result = (
            client.table("memories")
            .select("id, content, memory_type, importance, created_at")
            .eq("user_id", user_id)
            .eq("companion_id", persona_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception:
        return []
