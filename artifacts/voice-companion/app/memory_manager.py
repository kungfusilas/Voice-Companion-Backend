"""
memory_manager.py — LegacyBond AI

Builds a tiered, token-budgeted memory context block that gets appended to the
chat system prompt. This is the single place that assembles "everything we
remember about this user" into one text blob, separate from the per-message
retrieval done in memory.py / graphiti_memory.py.

Tiering:
  TIER 1 (always included — the durable identity layer):
    - personality_map row (Big Five snapshot)
    - top 20 user_core_facts, sorted by updated_at desc
    - onboarding_answers for the user (best-effort; table may not exist yet)

  TIER 2 (included only if there is still room in the ~2000 token budget):
    - last 7 session_debriefs, sorted by created_at desc
    - future_memories with an upcoming target_date within the next 60 days
    - most recent weekly_insights row

All Supabase reads are best-effort: any failure (missing table, network error,
bad response) is logged and treated as "no data for this section" so a single
broken tier never breaks the whole memory block.

Budget accounting uses a simple ~4 chars/token heuristic (no tokenizer
dependency) since this only needs to be a soft cap, not exact.
"""
import os
import logging
from datetime import date, datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_MAX_TOKENS = 2000
_CHARS_PER_TOKEN = 4
_MAX_CHARS = _MAX_TOKENS * _CHARS_PER_TOKEN


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def _sb_get(client: httpx.AsyncClient, table: str, params: dict) -> list:
    """Best-effort SELECT. Returns [] on any error (missing table, network, etc)."""
    try:
        resp = await client.get(
            f"{_sb_url()}/rest/v1/{table}",
            headers=_sb_headers(),
            params=params,
        )
        if resp.status_code in (200, 206):
            data = resp.json()
            return data if isinstance(data, list) else []
        logger.debug("memory_manager: %s select status=%d", table, resp.status_code)
    except Exception as exc:
        logger.debug("memory_manager: %s select failed (non-fatal): %s", table, exc)
    return []


def _fmt_personality(row: dict | None) -> str:
    if not row:
        return ""
    dims = [
        ("Openness", row.get("openness_score"), row.get("openness_label")),
        ("Conscientiousness", row.get("conscientiousness_score"), row.get("conscientiousness_label")),
        ("Extraversion", row.get("extraversion_score"), row.get("extraversion_label")),
        ("Agreeableness", row.get("agreeableness_score"), row.get("agreeableness_label")),
        ("Neuroticism", row.get("neuroticism_score"), row.get("neuroticism_label")),
    ]
    lines = [f"- {name}: {score} ({label})" for name, score, label in dims if score is not None]
    if not lines:
        return ""
    summary = row.get("overall_summary")
    block = "## PERSONALITY\n" + "\n".join(lines)
    if summary:
        block += f"\nSummary: {summary}"
    return block


def _fmt_core_facts(rows: list) -> str:
    if not rows:
        return ""
    lines = [f"- ({r.get('category', 'general')}) {r.get('fact', '').strip()}" for r in rows if r.get("fact")]
    if not lines:
        return ""
    return "## CORE FACTS\n" + "\n".join(lines)


def _fmt_onboarding(rows: list) -> str:
    if not rows:
        return ""
    lines = []
    for r in rows:
        q = r.get("question") or r.get("prompt")
        a = r.get("answer") or r.get("response")
        if a:
            lines.append(f"- {q + ': ' if q else ''}{a}")
    if not lines:
        return ""
    return "## ONBOARDING ANSWERS\n" + "\n".join(lines)


def _fmt_debriefs(rows: list) -> str:
    if not rows:
        return ""
    lines = []
    for r in rows:
        summary = r.get("summary") or r.get("debrief") or r.get("content")
        created = r.get("created_at", "")[:10]
        if summary:
            lines.append(f"- [{created}] {summary}")
    if not lines:
        return ""
    return "## RECENT SESSION DEBRIEFS\n" + "\n".join(lines)


def _fmt_future_memories(rows: list) -> str:
    if not rows:
        return ""
    lines = []
    for r in rows:
        desc = r.get("description")
        target = r.get("target_date")
        if desc:
            lines.append(f"- {desc}" + (f" (around {target})" if target else ""))
    if not lines:
        return ""
    return "## UPCOMING EVENTS\n" + "\n".join(lines)


def _fmt_weekly_insight(row: dict | None) -> str:
    if not row:
        return ""
    content = row.get("summary") or row.get("insight") or row.get("content")
    if not content:
        return ""
    return "## LATEST WEEKLY INSIGHT\n" + str(content)


async def get_memory_context(user_id: str, companion_id: str) -> str:
    """
    Build the tiered memory context block for injection into the system prompt.

    Returns an empty string if nothing is available or user_id is falsy —
    never raises, since this must never break the chat pipeline.
    """
    if not user_id:
        return ""

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            # ── TIER 1 — always fetched ────────────────────────────────────
            personality_rows, core_facts_rows, onboarding_rows = await _gather(
                _sb_get(client, "personality_map", {
                    "user_id": f"eq.{user_id}", "select": "*", "limit": "1",
                }),
                _sb_get(client, "user_core_facts", {
                    "user_id": f"eq.{user_id}", "select": "category,fact,updated_at",
                    "order": "updated_at.desc", "limit": "20",
                }),
                _sb_get(client, "onboarding_answers", {
                    "user_id": f"eq.{user_id}", "select": "*",
                }),
            )
            personality_row = personality_rows[0] if personality_rows else None

            tier1_sections = [
                _fmt_personality(personality_row),
                _fmt_core_facts(core_facts_rows),
                _fmt_onboarding(onboarding_rows),
            ]
            tier1_sections = [s for s in tier1_sections if s]
            block = "\n\n".join(tier1_sections)

            # ── TIER 2 — only if there's still budget left ──────────────────
            remaining = _MAX_CHARS - len(block)
            if remaining > 200:
                today = date.today()
                horizon = (today + timedelta(days=60)).isoformat()

                debrief_rows, future_rows, weekly_rows = await _gather(
                    _sb_get(client, "session_debriefs", {
                        "user_id": f"eq.{user_id}", "select": "*",
                        "order": "created_at.desc", "limit": "7",
                    }),
                    _sb_get(client, "future_memories", {
                        "user_id": f"eq.{user_id}", "select": "*",
                        "target_date": f"gte.{today.isoformat()}",
                        "and": f"(target_date.lte.{horizon})",
                    }),
                    _sb_get(client, "weekly_insights", {
                        "user_id": f"eq.{user_id}", "select": "*",
                        "order": "created_at.desc", "limit": "1",
                    }),
                )
                weekly_row = weekly_rows[0] if weekly_rows else None

                tier2_sections = [
                    _fmt_debriefs(debrief_rows),
                    _fmt_future_memories(future_rows),
                    _fmt_weekly_insight(weekly_row),
                ]
                tier2_block = "\n\n".join(s for s in tier2_sections if s)

                if tier2_block:
                    combined = f"{block}\n\n{tier2_block}" if block else tier2_block
                    # Only keep tier 2 if it still fits the overall budget;
                    # otherwise truncate tier 2 to what remains.
                    if len(combined) <= _MAX_CHARS:
                        block = combined
                    else:
                        block = combined[:_MAX_CHARS].rstrip()

            return block
    except Exception as exc:
        logger.warning("memory_manager: get_memory_context failed (non-fatal) user=%s: %s", user_id, exc)
        return ""


async def _gather(*coros):
    import asyncio
    return await asyncio.gather(*coros)
