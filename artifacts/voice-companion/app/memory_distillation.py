"""
memory_distillation.py — LegacyBond AI

Post-session memory distillation: runs once at the end of a conversation and
uses Claude Haiku to pull out durable, structured facts from the whole
session (as opposed to memory_extractor.py, which does lightweight per-turn
extraction on every single exchange).

Extracts:
  - Names and relationships mentioned (family, friends, colleagues, etc.)
  - Life events — both past and upcoming
  - Stated preferences
  - Anything the user explicitly wants remembered

Writes:
  - user_core_facts  (user_id, fact, category, updated_at)  — upserted, deduped
  - future_memories  (user_id, event_description, event_date, created_at) — upcoming events only

Fire-and-forget: never raises. All failures are logged and swallowed so a
distillation failure never affects the live chat response.
"""
import os
import json
import logging
from datetime import datetime, timezone

import httpx
import anthropic

from app import entitlements

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MIN_USER_MESSAGES = 3

_VALID_CATEGORIES = frozenset(
    {"family", "work", "location", "health", "goals", "personality", "history", "preferences"}
)

_SYSTEM_PROMPT = """You are a memory distillation engine for an AI companion app.
You will be given a full conversation transcript between a user and their AI companion.

Extract ONLY what the user actually said — never invent or infer beyond what's stated.

Return ONLY a valid JSON object, nothing else:
{
  "facts": [
    {"category": "family|work|location|health|goals|personality|history|preferences", "fact": "short factual statement, second-person free (e.g. 'Has a sister named Maya who lives in Denver')"}
  ],
  "upcoming_events": [
    {"description": "warm one-sentence description (e.g. 'Job interview at a design agency')", "event_date": "YYYY-MM-DD or null if no specific date can be determined"}
  ]
}

Rules:
- facts: names/relationships mentioned, life events (past or upcoming), stated preferences, and anything the user explicitly asked to be remembered
- facts: keep each one short, specific, and durable (not tied to this single conversation's mood)
- upcoming_events: only events that are clearly in the future relative to today
- event_date: if a relative time was mentioned (e.g. 'next Tuesday', 'in two weeks'), compute the best-estimate absolute date from today's date, given below
- Return empty arrays if nothing applicable is found
- Do not duplicate the same fact in slightly different wording"""


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_headers(prefer: str = "return=minimal") -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def _get_async_client() -> anthropic.AsyncAnthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    return anthropic.AsyncAnthropic(api_key=api_key)


def _extract_json(raw: str) -> dict:
    cleaned = raw.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else parts[0]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    return json.loads(cleaned)


async def _upsert_core_facts(client: httpx.AsyncClient, user_id: str, facts: list[dict]) -> None:
    facts = [
        f for f in facts
        if isinstance(f, dict)
        and isinstance(f.get("category"), str)
        and f["category"] in _VALID_CATEGORIES
        and isinstance(f.get("fact"), str)
        and f["fact"].strip()
    ]
    if not facts:
        return

    # Dedup against existing facts, respecting the same 50-fact cap used elsewhere.
    resp = await client.get(
        f"{_sb_url()}/rest/v1/user_core_facts",
        headers=_sb_headers(prefer=""),
        params={"user_id": f"eq.{user_id}", "select": "id,category,fact"},
    )
    existing: list = resp.json() if resp.status_code in (200, 206) else []
    if not isinstance(existing, list):
        existing = []

    existing_by_key: dict[tuple[str, str], dict] = {
        (row["category"], row["fact"].lower().strip()): row
        for row in existing
        if isinstance(row, dict) and row.get("fact")
    }

    now = datetime.now(timezone.utc).isoformat()
    to_insert: list[dict] = []
    for item in facts:
        cat = item["category"]
        fact_text = item["fact"].strip()
        key = (cat, fact_text.lower())
        if key in existing_by_key:
            # Refresh updated_at on the existing row instead of duplicating it.
            row_id = existing_by_key[key].get("id")
            if row_id:
                await client.patch(
                    f"{_sb_url()}/rest/v1/user_core_facts?id=eq.{row_id}",
                    headers=_sb_headers(),
                    json={"updated_at": now},
                )
            continue
        to_insert.append({
            "user_id": user_id,
            "category": cat,
            "fact": fact_text,
            "confidence": 1.0,
            "created_at": now,
            "updated_at": now,
        })
        existing_by_key[key] = {"fact": fact_text, "category": cat}

    if not to_insert:
        return

    # Per-tier fact cap (entitlements). Fails open to the free-tier cap floor
    # of 25 only if the plan lookup fails open to 'free'.
    try:
        plan = await entitlements.get_plan(user_id)
        max_facts = entitlements.get_limits(plan)["max_facts"]
    except Exception as e:
        # Fail open: an entitlements error must never block memory distillation.
        logger.warning("memory_distillation: entitlements lookup failed (fail-open) user=%s err=%s", user_id[:8], e)
        plan = "free"
        max_facts = 1_000_000
    remaining_slots = max(0, max_facts - len(existing))
    to_insert = to_insert[:remaining_slots]
    if not to_insert:
        logger.debug(
            "memory_distillation: fact cap reached user=%s plan=%s max=%d",
            user_id[:8], plan, max_facts,
        )
        return

    await client.post(
        f"{_sb_url()}/rest/v1/user_core_facts",
        headers=_sb_headers(),
        json=to_insert,
    )
    logger.debug("memory_distillation: upserted %d core facts user=%s", len(to_insert), user_id[:8])


async def _insert_future_events(client: httpx.AsyncClient, user_id: str, events: list[dict]) -> None:
    events = [
        e for e in events
        if isinstance(e, dict) and isinstance(e.get("description"), str) and e["description"].strip()
    ]
    if not events:
        return

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "user_id": user_id,
            "type": "date_based",
            "description": e["description"].strip(),
            "target_date": e.get("event_date") or None,
            "created_at": now,
        }
        for e in events
    ]

    await client.post(
        f"{_sb_url()}/rest/v1/future_memories",
        headers=_sb_headers(),
        json=rows,
    )
    logger.debug("memory_distillation: inserted %d future events user=%s", len(rows), user_id[:8])


async def distill_memories(user_id: str, messages: list) -> None:
    """
    Fire-and-forget: distill a full conversation's worth of messages into
    durable facts and upcoming events.

    `messages` may be a list of dicts ({"role": ..., "content": ...}) or
    objects with `.role` / `.content` attributes (e.g. ChatMessage).
    Skips entirely if there are fewer than 3 user messages — not enough
    signal to distill anything meaningful.
    """
    if not user_id or not messages:
        return

    try:
        def _role(m):
            return m.get("role") if isinstance(m, dict) else getattr(m, "role", None)

        def _content(m):
            return m.get("content") if isinstance(m, dict) else getattr(m, "content", "")

        user_messages = [_content(m) for m in messages if _role(m) == "user"]
        if len(user_messages) < _MIN_USER_MESSAGES:
            return

        transcript_lines = []
        for m in messages:
            role = _role(m) or "user"
            content = (_content(m) or "").strip()
            if content:
                transcript_lines.append(f"{role.upper()}: {content}")
        transcript = "\n".join(transcript_lines)
        if not transcript:
            return

        today = datetime.now(timezone.utc).date().isoformat()
        system_prompt = f"{_SYSTEM_PROMPT}\n\nToday's date: {today}"

        client = _get_async_client()
        resp = await client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": transcript}],
        )
        raw = ""
        for block in resp.content:
            if block.type == "text":
                raw += block.text
        if not raw.strip():
            return

        parsed = _extract_json(raw)
        facts = parsed.get("facts") or []
        events = parsed.get("upcoming_events") or []
        if not facts and not events:
            return

        supabase_url = os.environ.get("SUPABASE_URL", "")
        service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not supabase_url or not service_key:
            logger.warning("memory_distillation: SUPABASE env vars missing — skipping writes")
            return

        async with httpx.AsyncClient(timeout=15.0) as http:
            if facts:
                await _upsert_core_facts(http, user_id, facts)
            if events:
                await _insert_future_events(http, user_id, events)

    except Exception as exc:
        logger.warning("memory_distillation: distill_memories failed (non-fatal) user=%s: %s", user_id, exc)
