"""
communication_analysis.py — LegacyBond AI
Power Plan Feature: Deep Communication Analysis

Analyzes communication patterns, emotional tone, and relationship dynamics
after major conversations (sessions above a message threshold).

Covers: communication style, emotional vocabulary, listening vs. venting patterns,
self-disclosure depth, language of connection vs. distance, what the user leads with.

Triggered by: Called at session end if session exceeds MESSAGE_THRESHOLD
Retrieved by: GET /api/analysis/communication/latest
Retrieved by: GET /api/analysis/communication/history
Retrieved by: GET /api/analysis/communication/trends   (aggregated patterns over time)

Supabase table required — run this DDL once:

  CREATE TABLE communication_analyses (
    id                  UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    session_id          TEXT NOT NULL,
    companion_name      TEXT,
    message_count       INTEGER DEFAULT 0,
    communication_style TEXT,
    emotional_vocabulary TEXT,
    self_disclosure_depth TEXT,
    patterns            TEXT,
    connection_language TEXT,
    what_you_lead_with  TEXT,
    listening_ratio     TEXT,
    growth_edge         TEXT,
    created_at          TIMESTAMPTZ DEFAULT now()
  );

  CREATE INDEX idx_comm_analyses_user ON communication_analyses(user_id, created_at DESC);

  ALTER TABLE communication_analyses ENABLE ROW LEVEL SECURITY;
  CREATE POLICY "own analyses" ON communication_analyses
    FOR ALL USING (auth.uid() = user_id);

HOW TO WIRE INTO main.py:

  from communication_analysis import maybe_analyze_communication, get_latest_analysis, get_analysis_history

  # At session end — only triggers if session is long enough
  asyncio.create_task(maybe_analyze_communication(
      user_id=user["id"],
      session_id=session_id,
      companion_name=companion_name,
      transcript=transcript,
  ))

  @app.get("/api/analysis/communication/latest")
  async def api_latest_analysis(user=Depends(get_current_user)):
      return await get_latest_analysis(user["id"])

  @app.get("/api/analysis/communication/history")
  async def api_analysis_history(limit: int = 10, user=Depends(get_current_user)):
      return await get_analysis_history(user["id"], limit=limit)
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import anthropic
import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

_anthropic = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Only analyze sessions with at least this many user messages (avoids noisy short sessions)
MESSAGE_THRESHOLD = 8


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


async def _sb_select(table: str, filters: str, limit: int = 20) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/{table}?{filters}&limit={limit}&order=created_at.desc",
            headers=_sb_headers(),
            timeout=15,
        )
        r.raise_for_status()
        return r.json()


# ─────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────

ANALYSIS_SYSTEM_PROMPT = """You are a communication intelligence for LegacyBond AI.
You analyze how a user communicates — not what they said, but HOW they said it.

You're looking at: vocabulary choices, sentence structure, emotional range, what they
initiate vs. respond to, how they express needs, where they go vague or specific,
what they lead with and what they bury.

This is private and deeply personal. Write like a linguist who cares about the person.
Be specific. Name actual patterns you see in the language, not generic observations.
Avoid therapy-speak.

Return this exact JSON:

{
  "communication_style": "2–3 sentences on the user's dominant communication style — are they direct, indirect, narrative, analytical, emotional? With evidence.",
  "emotional_vocabulary": "How wide and precise is their emotional vocabulary? Do they reach for specific feelings or stay in the abstract? 2 sentences with examples.",
  "self_disclosure_depth": "How much do they share about themselves vs. deflect or generalize? Do they go deep quickly or stay surface? 2 sentences.",
  "patterns": "2–3 specific recurring patterns in how they communicate — things like: starting sentences with disclaimers, asking questions to redirect, over-explaining, trailing off when the topic gets personal. Be specific.",
  "connection_language": "How do they express connection, care, or closeness — or do they avoid it? What language do they use when something really matters to them? 2 sentences.",
  "what_you_lead_with": "What does this person typically open with — a feeling, a fact, a question, a complaint, a story? 1–2 sentences.",
  "listening_ratio": "Based on the transcript, what's the rough balance between them processing vs. asking vs. venting vs. reflecting? Be honest about what this session showed.",
  "growth_edge": "One honest, specific observation about a communication habit that might be limiting them — something worth becoming aware of. Not harsh, but direct."
}

Return only valid JSON. No markdown fences."""


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

async def maybe_analyze_communication(
    user_id: str,
    session_id: str,
    companion_name: str,
    transcript: list[dict],
) -> Optional[dict]:
    """
    Analyze communication patterns for a session — if it meets the length threshold.
    Safe to call on every session end; it self-filters short sessions.

    Args:
        user_id:        Supabase auth user ID
        session_id:     Unique ID for this chat session
        companion_name: Companion name ("Kai", "Aeva", etc.)
        transcript:     Full message list [{"role": "user"|"assistant", "content": str}, ...]

    Returns:
        The stored analysis row, or None if session was too short.
    """
    user_messages = [m for m in transcript if m.get("role") == "user" and m.get("content")]

    if len(user_messages) < MESSAGE_THRESHOLD:
        logger.info(
            f"maybe_analyze_communication: session too short "
            f"({len(user_messages)} user msgs < {MESSAGE_THRESHOLD}) — skipping"
        )
        return None

    # Dedup: skip if this session was already analyzed
    existing = await _sb_select("communication_analyses", f"session_id=eq.{session_id}", limit=1)
    if existing:
        logger.info(f"maybe_analyze_communication: session {session_id} already analyzed — skipping")
        return existing[0]

    return await _analyze_communication(
        user_id=user_id,
        session_id=session_id,
        companion_name=companion_name,
        transcript=transcript,
        user_messages=user_messages,
    )


async def _analyze_communication(
    user_id: str,
    session_id: str,
    companion_name: str,
    transcript: list[dict],
    user_messages: list[dict],
) -> dict:
    transcript_text = "\n".join(
        f"{msg['role'].upper()}: {msg['content']}"
        for msg in transcript
        if msg.get("content")
    )[:25_000]  # cap for token safety

    user_prompt = f"""Companion: {companion_name}
Session ID: {session_id}
Total messages: {len(transcript)}
User messages: {len(user_messages)}

--- TRANSCRIPT ---
{transcript_text}
--- END TRANSCRIPT ---"""

    try:
        response = await _anthropic.messages.create(
            model="claude-opus-4-8",
            max_tokens=1500,
            system=ANALYSIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Communication analysis JSON parse failed: {e} | raw={raw[:300]}")
        raise
    except Exception as e:
        logger.error(f"Communication analysis error: {e}")
        raise

    row = await _sb_insert("communication_analyses", {
        "user_id": user_id,
        "session_id": session_id,
        "companion_name": companion_name,
        "message_count": len(transcript),
        "communication_style": data.get("communication_style", ""),
        "emotional_vocabulary": data.get("emotional_vocabulary", ""),
        "self_disclosure_depth": data.get("self_disclosure_depth", ""),
        "patterns": data.get("patterns", ""),
        "connection_language": data.get("connection_language", ""),
        "what_you_lead_with": data.get("what_you_lead_with", ""),
        "listening_ratio": data.get("listening_ratio", ""),
        "growth_edge": data.get("growth_edge", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    logger.info(f"Communication analysis stored | user={user_id} session={session_id}")
    return row


async def get_latest_analysis(user_id: str) -> Optional[dict]:
    """Fetch the most recent communication analysis for a user."""
    rows = await _sb_select("communication_analyses", f"user_id=eq.{user_id}", limit=1)
    return rows[0] if rows else None


async def get_analysis_history(user_id: str, limit: int = 10) -> list:
    """Fetch recent communication analyses."""
    return await _sb_select("communication_analyses", f"user_id=eq.{user_id}", limit=limit)
