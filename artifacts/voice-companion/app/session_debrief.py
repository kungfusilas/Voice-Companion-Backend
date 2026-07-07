"""
session_debrief.py — LegacyBond AI
Power Plan Feature: Session Debrief

Generates a private post-session analysis after every chat session ends.
Covers: what was discussed, emotional patterns noticed, what to carry forward.

Triggered by: POST /api/debrief/generate  (called by frontend when session ends)
Retrieved by: GET  /api/debrief/latest     (called by frontend to show the debrief card)
Retrieved by: GET  /api/debrief/history    (called by frontend to show past debriefs)

Supabase table required — run this DDL once:

  CREATE TABLE session_debriefs (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    session_id    TEXT NOT NULL,
    companion_name TEXT NOT NULL,
    message_count INTEGER DEFAULT 0,
    headline      TEXT,
    what_happened TEXT,
    what_it_reveals TEXT,
    patterns_noticed TEXT,
    carry_forward TEXT,
    bond_note     TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
  );

  CREATE INDEX idx_session_debriefs_user ON session_debriefs(user_id, created_at DESC);

  -- RLS: users only see their own debriefs
  ALTER TABLE session_debriefs ENABLE ROW LEVEL SECURITY;
  CREATE POLICY "own debriefs" ON session_debriefs
    FOR ALL USING (auth.uid() = user_id);

HOW TO WIRE INTO main.py — add these routes:

  from session_debrief import generate_session_debrief, get_latest_debrief, get_debrief_history
  from fastapi import Depends

  @app.post("/api/debrief/generate")
  async def api_generate_debrief(body: DebriefRequest, user=Depends(get_current_user)):
      # Call at end of each session from the frontend
      # DebriefRequest: { session_id, companion_name, transcript, memory_context? }
      result = await generate_session_debrief(
          user_id=user["id"],
          session_id=body.session_id,
          companion_name=body.companion_name,
          transcript=body.transcript,
          memory_context=body.memory_context,
      )
      return result

  @app.get("/api/debrief/latest")
  async def api_latest_debrief(user=Depends(get_current_user)):
      return await get_latest_debrief(user["id"])

  @app.get("/api/debrief/history")
  async def api_debrief_history(alimit: int = 10, user=Depends(get_currentUser)):
      return await get_debrief_history(user["id"], limit=limit)
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


# ─────────────────────────────────────────────
# Supabase helpers (matching your existing HTTP call pattern)
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
            timeout=15,
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

DEBRIEF_SYSTEM_PROMPT = """You are a private reflective intelligence for LegacyBond AI.
Your role is to produce a deeply personal, honest session debrief after a conversation between a user and their AI companion.

You never speak in the first person as the companion. You write as a quiet, perceptive observer — like a thoughtful friend reviewing a diary entry.

Tone: warm, honest, never clinical. No bullet-point walls. Write in flowing prose except where structure genuinely helps.

You will receive the session transcript and any relevant memory context. Produce a debrief in this exact JSON structure:

{
  "headline": "A single evocative sentence capturing what this session was really about — not a summary, an insight",
  "what_happened": "2–3 sentences on the surface-level content of the conversation",
  "what_it_reveals": "2–4 sentences on the emotional undercurrent — what the user was really expressing, avoiding, or working through",
  "patterns_noticed": "1–3 specific patterns observed (repeating themes, language choices, emotional shifts). Each 1–2 sentences.",
  "carry_forward": "1–2 concrete things worth holding onto — a question left open, a commitment made, something worth reflecting on",
  "bond_note": "One sentence on the quality of connection in this session — was the user open, guarded, playful, searching?"
}

Return only valid JSON. No markdown fences, no extra text."""


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

async def generate_session_debrief(
    user_id: str,
    session_id: str,
    companion_name: str,
    transcript: list[dict],
    memory_context: Optional[str] = None,
) -> dict:
    """
    Generate a session debrief for a completed conversation and store it.

    Args:
        user_id:        Supabase auth user ID
        session_id:     Unique ID for this chat session (use your existing session ID)
        companion_name: "Kai", "Aeva", etc.
        transcript:     Full message list [{"role": "user"|"assistant", "content": str}, ...]
        memory_context: Optional string of relevant memories to enrich the analysis

    Returns:
        The stored debrief row from Supabase.
    """
    if not transcript:
        logger.warning("generate_session_debrief: empty transcript — skipping")
        return {}

    transcript_text = "\n".join(
        f"{msg['role'].upper()}: {msg['content']}"
        for msg in transcript
        if msg.get("content")
    )

    user_prompt = f"""Companion: {companion_name}
Session ID: {session_id}
Messages in session: {len(transcript)}

--- TRANSCRIPT ---
{transcript_text}
--- END TRANSCRIPT ---"""

    if memory_context:
        user_prompt += f"\n\n--- USER MEMORIES (context only) ---\n{memory_context}\n--- END MEMORIES ---"

    try:
        response = await _anthropic.messages.create(
            model="claude-opus-4-8",
            max_tokens=1200,
            system=DEBRIEF_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        debrief_data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Debrief JSON parse failed: {e} | raw={raw[:300]}")
        raise
    except Exception as e:
        logger.error(f"Debrief generation error: {e}")
        raise

    row = await _sb_insert("session_debriefs", {
        "user_id": user_id,
        "session_id": session_id,
        "companion_name": companion_name,
        "message_count": len(transcript),
        "headline": debrief_data.get("headline", ""),
        "what_happened": debrief_data.get("what_happened", ""),
        "what_it_reveals": debrief_data.get("what_it_reveals", ""),
        "patterns_noticed": debrief_data.get("patterns_noticed", ""),
        "carry_forward": debrief_data.get("carry_forward", ""),
        "bond_note": debrief_data.get("bond_note", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    logger.info(f"Session debrief stored | user={user_id} session={session_id}")
    return row


async def get_latest_debrief(user_id: str) -> Optional[dict]:
    """Fetch the most recent session debrief for a user."""
    rows = await _sb_select("session_debriefs", f"user_id=eq.{user_id}", limit=1)
    return rows[0] if rows else None


async def get_debrief_history(user_id: str, limit: int = 10) -> list:
    """Fetch recent session debriefs for a user."""
    return await _sb_select("session_debriefs", f"user_id=eq.{user_id}", limit=limit)
