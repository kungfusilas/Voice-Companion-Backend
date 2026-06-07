"""
Vector memory store.

Embeddings: Voyage AI voyage-3 (1024 dimensions) via httpx
Storage:    Supabase pgvector
Extraction: Claude Haiku decides what's worth saving
"""
import os
import json
import asyncio
import httpx
from supabase import create_client, Client

_client: Client | None = None

_VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
_VOYAGE_MODEL = "voyage-3"

_SHOULD_REMEMBER_PROMPT = (
    "Does this conversation exchange contain anything worth a companion remembering long-term? "
    "Look for: facts about the user (name, job, family, pets, location), "
    "preferences (likes/dislikes, hobbies), emotional moments (confessions, vulnerable shares, breakthroughs), "
    "relationship milestones, or recurring themes. "
    'If yes, return JSON: {"should_save": true, "content": "concise memory in 1-2 sentences written from '
    'companion POV e.g. The user told me their dog is named Biscuit", '
    '"type": "fact|emotion|preference|event|relationship", "importance": 1-10}. '
    'If nothing worth saving, return {"should_save": false}. '
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
    try:
        turn = f"User: {user_msg}\nCompanion: {companion_msg}"
        raw = await claude.send_message(
            system_prompt=_SHOULD_REMEMBER_PROMPT,
            history=[],
            user_message=turn,
            model="claude-haiku-4-5",
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
            return None
        return result
    except Exception:
        return None


async def save_memory(
    user_id: str,
    companion_id: str,
    content: str,
    memory_type: str = "fact",
    importance: int = 5,
) -> dict:
    """
    Embed content and insert into the pgvector memories table.
    Silently returns {} on any error so it never breaks chat flow.
    """
    try:
        embedding = await embed(content)
        # PostgreSQL vector literal: "[x,y,z,...]"
        vec_str = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
        client = _get_client()
        result = client.table("memories").insert({
            "user_id": user_id,
            "companion_id": companion_id,
            "content": content,
            "memory_type": memory_type,
            "embedding": vec_str,
            "importance": max(1, min(10, int(importance))),
        }).execute()
        return result.data[0] if result.data else {}
    except Exception:
        return {}


async def retrieve_memories(
    user_id: str,
    companion_id: str,
    query_text: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Find the top_k most semantically similar memories via cosine similarity.
    Updates access stats fire-and-forget. Returns [] on any error.
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
        if memories:
            ids = [m["id"] for m in memories if m.get("id")]
            if ids:
                asyncio.create_task(_update_access_stats(ids))
        return memories
    except Exception:
        return []


async def _update_access_stats(memory_ids: list[str]) -> None:
    """Increment access_count and refresh last_accessed_at for retrieved memories."""
    try:
        client = _get_client()
        client.rpc("increment_memory_access", {"memory_ids": memory_ids}).execute()
    except Exception:
        pass


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
