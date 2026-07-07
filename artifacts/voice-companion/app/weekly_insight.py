"""
weekly_insight.py — LegacyBond AI
Power Plan Feature: Weekly Insight Report

Generates a private weekly report covering 7 days of conversations.
Analyzes: emotional patterns, relationship health, goal progress, mindset shifts.

Triggered by: POST /api/insights/weekly/generate   (called by a scheduled job OR on-demand)
Retrieved by: GET  /api/insights/weekly/latest      (most recent report)
Retrieved by: GET  /api/insights/weekly/history     (past reports)

Supabase table required — run this DDL once:

  CREATE TABLE weekly_insights (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    week_start      DATE NOT NULL,
    week_end        DATE NOT NULL,
    session_count   INTEGER DEFAULT 0,
    message_count   INTEGER DEFAULT 0,
    emotional_tone  TEXT,
    key_themes      TEXT,
    relationship_health TEXT,
    goal_progress   TEXT,
    mindset_shifts  TEXT,
    growth_highlight TEXT,
    honest_observation TEXT,
    next_week_intention TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
  );

  CREATE UNIQUE INDEX idx_weekly_insights_user_week
    ON weekly_insights(user_id, week_start);

  CREATE INDEX idx_weekly_insights_user
    ON weekly_insights(user_id, created_at DESC);

  ALTER TABLE weekly_insights ENABLE ROW LEVEL SECURITY;
  CREATE POLICY "own insights" ON weekly_insights
    FOR ALL USING (auth.uid() = user_id);

HOW TO WIRE INTO main.py:

  from weekly_insight import generate_weekly_insight, get_latest_weekly_insight, get_weekly_insight_history
  from pydantic import BaseModel

  @app.post("/api/insights/weekly/generate")
  async def api_generate_weekly(user=Depends(get_current_user)):
      # Call this from a scheduled job (daily, checks if new week)
      # OR expose as on-demand endpoint for the user
      result = await generate_weekly_insight(user_id=user["id"])
      return result

  @app.get("/api/insights/weekly/latest")
  async def api_latest_weekly(user=Depends(get_current_user)):
      return await get_latest_weekly_insight(user["id"])

  @app.get("/api/insights/weekly/history")
  async def api_weekly_history(limit: int = 12, user=Depends(get_current_user)):
      return await get_weekly_insight_history(user["id"], limit=limit)

SCHEDULING: The simplest approach is to call generate_weekly_insight() from a background
task that runs on login if the user hasn't received a report this week. No cron required.
Add this check to your existing session-start logic:

  asyncio.create_task(_maybe_generate_weekly_insight(user_id))
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta, date
from typing import Optional

import anthropic
import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

_anthropic = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


# ─────────────────────────────────────────────
# Supabase helpers
# ─────────────────────────────────────────────

def _sb_headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def _sb_insert(table: str, payload: dict) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=_sb_headers(),
            json=payload,
            timeout=20,
        )
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else {}


async def _sb_upsert(table: str, payload: dict, on_conflict: str) -> dict:
    headers = {**_sb_headers(), "Prefer": f"resolution=merge-duplicates,return=representation"}
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={on_conflict}",
            headers=headers,
            json=payload,
            timeout=20,
        )
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else {}


async def _sb_select(table: str, filters: str, limit: int = 20) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/{table}?{filters}&limit={limit}&order=created_at.desc",
            headers=_sb_headers(),
            timeout=15,
        )
        r.raise_for_status()
        return r.json()


async def _fetch_week_conversations(user_id: str, week_start: date, week_end: date) -> list[dict]:
    """
    Fetch all messages from the past week by reading the conversations table.
    Each row has a session_id and a messages JSON array.
    Returns a flat list of message dicts with session_id injected.
    """
    start_iso = week_start.isoformat()
    end_iso = (week_end + timedelta(days=1)).isoformat()
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/conversations"
            f"?user_id=eq.{user_id}"
            f"&created_at=gte.{start_iso}"
            f"&created_at=lt.{end_iso}"
            f"&order=created_at.asc&limit=200",
            headers=_sb_headers(),
            timeout=20,
        )
        r.raise_for_status()
        sessions = r.json()

    # Flatten messages from all sessions, injecting session_id into each message
    all_messages = []
    for session in sessions:
        session_id = session.get("session_id", "")
        msgs = session.get("messages", []) or []
        if isinstance(msgs, str):
            try:
                msgs = json.loads(msgs)
            except Exception:
                msgs = []
        for m in msgs:
            if isinstance(m, dict):
                all_messages.append({**m, "session_id": session_id})
    return all_messages


# ─────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────

WEEKLY_SYSTEM_PROMPT = """You are LegacyBond's weekly insight intelligence.
You have access to a week of conversations between a user and their AI companion.
Your job is to surface patterns, growth, and honest observations the user may not have noticed themselves.

This is private. The user is the only audience. Write as if you know them well.
Be honest without being harsh. Be warm without being sycophantic.
Avoid generic self-help language. Be specific to what actually happened this week.

Return this exact JSON structure:

{
  "emotional_tone": "2–3 sentences on the overall emotional register of the week — the mood underneath the conversations",
  "key_themes": "The 2–4 topics or concerns that came up repeatedly. Each theme in 1 sentence.",
  "relationship_health": "How did the user talk about the relationships in their life this week? Any shifts, tensions, or bright spots? 2–3 sentences.",
  "goal_progress": "Did the user mention goals, plans, or intentions? What movement happened — or didn't? 2–3 sentences. If no goals were mentioned, say so honestly.",
  "mindset_shifts": "Did anything seem to shift in how the user was thinking or feeling across the week? Even small shifts count. 2–3 sentences.",
  "growth_highlight": "One specific moment, exchange, or realization from the week worth naming as a sign of growth or self-awareness.",
  "honest_observation": "Something the user might not want to hear but probably needs to — a pattern worth examining, something they're avoiding, or a question worth sitting with. 2–3 sentences. Be gentle but direct.",
  "next_week_intention": "One grounded, specific intention for the coming week based on what this week revealed. Not a to-do list — a direction."
}

Return only valid JSON. No markdown fences."""


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def _get_week_bounds() -> tuple[date, date]:
    """Returns Monday–Sunday for the most recently completed week."""
    today = datetime.now(timezone.utc).date()
    # Go back to last Monday (or current week if today is Monday)
    days_since_monday = today.weekday()
    week_end = today - timedelta(days=days_since_monday + 1)   # last Sunday
    week_start = week_end - timedelta(days=6)                   # last Monday
    return week_start, week_end


async def _already_generated(user_id: str, week_start: date) -> bool:
    rows = await _sb_select(
        "weekly_insights",
        f"user_id=eq.{user_id}&week_start=eq.{week_start.isoformat()}",
        limit=1,
    )
    return len(rows) > 0


async def generate_weekly_insight(user_id: str, force: bool = False) -> Optional[dict]:
    """
    Generate the weekly insight report for the past 7 days.
    Idempotent — won't regenerate if already done for this week (unless force=True).

    Args:
        user_id: Supabase auth user ID
        force:   Regenerate even if a report already exists for this week

    Returns:
        The stored insight row, or None if skipped.
    """
    week_start, week_end = _get_week_bounds()

    if not force and await _already_generated(user_id, week_start):
        logger.info(f"Weekly insight already exists for user={user_id} week={week_start}")
        return await get_latest_weekly_insight(user_id)

    messages = await _fetch_week_conversations(user_id, week_start, week_end)

    if not messages:
        logger.info(f"No messages found for user={user_id} week={week_start} — skipping insight")
        return None

    # Build conversation digest (summarise if very long to stay within token limits)
    session_ids = set()
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")[:800]  # cap per message
        sid = msg.get("session_id", "")
        if sid:
            session_ids.add(sid)
        lines.append(f"{role.upper()}: {content}")

    conversation_digest = "\n".join(lines)
    # Keep total under ~80k chars to stay safe with context
    if len(conversation_digest) > 80_000:
        conversation_digest = conversation_digest[:80_000] + "\n[... earlier messages omitted for length ...]"

    user_prompt = f"""Week: {week_start.strftime('%B %d')} – {week_end.strftime('%B %d, %Y')}
Sessions this week: {len(session_ids)}
Messages this week: {len(messages)}

--- CONVERSATIONS ---
{conversation_digest}
--- END ---"""

    try:
        response = await _anthropic.messages.create(
            model="claude-opus-4-8",
            max_tokens=2000,
            system=WEEKLY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        insight_data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Weekly insight JSON parse failed: {e} | raw={raw[:300]}")
        raise
    except Exception as e:
        logger.error(f"Weekly insight generation error: {e}")
        raise

    row = await _sb_upsert("weekly_insights", {
        "user_id": user_id,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "session_count": len(session_ids),
        "message_count": len(messages),
        "emotional_tone": insight_data.get("emotional_tone", ""),
        "key_themes": insight_data.get("key_themes", ""),
        "relationship_health": insight_data.get("relationship_health", ""),
        "goal_progress": insight_data.get("goal_progress", ""),
        "mindset_shifts": insight_data.get("mindset_shifts", ""),
        "growth_highlight": insight_data.get("growth_highlight", ""),
        "honest_observation": insight_data.get("honest_observation", ""),
        "next_week_intention": insight_data.get("next_week_intention", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="user_id,week_start")

    logger.info(f"Weekly insight stored | user={user_id} week={week_start}")
    return row


async def maybe_generate_weekly_insight(user_id: str) -> None:
    """
    Fire-and-forget wrapper for use in asyncio.create_task().
    Call this at session start to trigger the weekly report if it's due.
    """
    try:
        await generate_weekly_insight(user_id)
    except Exception as e:
        logger.error(f"maybe_generate_weekly_insight failed silently: {e}")


async def get_latest_weekly_insight(user_id: str) -> Optional[dict]:
    rows = await _sb_select("weekly_insights", f"user_id=eq.{user_id}", limit=1)
    return rows[0] if rows else None


async def get_weekly_insight_history(user_id: str, limit: int = 12) -> list:
    return await _sb_select("weekly_insights", f"user_id=eq.{user_id}", limit=limit)
