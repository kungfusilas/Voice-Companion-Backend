"""
personality_map.py — LegacyBond AI
Power Plan Feature: Personality Map

Builds a live Big Five personality profile from the user's actual conversations —
not a quiz. Updates incrementally after every session. Evolves as the user does.

Big Five dimensions: Openness, Conscientiousness, Extraversion, Agreeableness, Neuroticism

Each dimension is scored 1–100 with a qualitative label and supporting evidence
drawn from real conversation moments.

Triggered by: Called internally at session end (after debrief) — no user action needed
Retrieved by: GET /api/personality/map      (current snapshot)
Retrieved by: GET /api/personality/history  (how the map has evolved over time)

Supabase table required — run this DDL once:

  CREATE TABLE personality_map (
    id                    UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id               UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    openness_score        INTEGER CHECK (openness_score BETWEEN 1 AND 100),
    openness_label        TEXT,
    openness_evidence     TEXT,
    conscientiousness_score INTEGER CHECK (conscientiousness_score BETWEEN 1 AND 100),
    conscientiousness_label TEXT,
    conscientiousness_evidence TEXT,
    extraversion_score    INTEGER CHECK (extraversion_score BETWEEN 1 AND 100),
    extraversion_label    TEXT,
    extraversion_evidence TEXT,
    agreeableness_score   INTEGER CHECK (agreeableness_score BETWEEN 1 AND 100),
    agreeableness_label   TEXT,
    agreeableness_evidence TEXT,
    neuroticism_score     INTEGER CHECK (neuroticism_score BETWEEN 1 AND 100),
    neuroticism_label     TEXT,
    neuroticism_evidence  TEXT,
    overall_summary       TEXT,
    sessions_analyzed     INTEGER DEFAULT 0,
    created_at            TIMESTAMPTZ DEFAULT now(),
    updated_at            TIMESTAMPTZ DEFAULT now()
  );

  -- One row per user (upsert pattern)
  CREATE UNIQUE INDEX idx_personality_map_user ON personality_map(user_id);

  ALTER TABLE personality_map ENABLE ROW LEVEL SECURITY;
  CREATE POLICY "own personality" ON personality_map
    FOR ALL USING (auth.uid() = user_id);

  -- Snapshot history table (append-only, for the evolution view)
  CREATE TABLE personality_map_history (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    snapshot        JSONB NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
  );

  CREATE INDEX idx_personality_history_user ON personality_map_history(user_id, created_at DESC);

  ALTER TABLE personality_map_history ENABLE ROW LEVEL SECURITY;
  CREATE POLICY "own history" ON personality_map_history
    FOR ALL USING (auth.uid() = user_id);

HOW TO WIRE INTO main.py:

  from personality_map import update_personality_map, get_personality_map, get_personality_history

  # Call this at session end, after the debrief (fire-and-forget)
  asyncio.create_task(update_personality_map(
      user_id=user["id"],
      session_transcript=transcript,
      existing_map=await get_personality_map(user["id"]),
  ))

  @app.get("/api/personality/map")
  async def api_personality_map(user=Depends(get_current_user)):
      return await get_personality_map(user["id"])

  @app.get("/api/personality/history")
  async def api_personality_history(limit: int = 20, user=Depends(get_current_user)):
      return await get_personality_history(user["id"], limit=limit)
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
# Supabase helpers
# ─────────────────────────────────────────────

def _sb_headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


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


async def _sb_select_one(table: str, filters: str) -> Optional[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/{table}?{filters}&limit=1",
            headers=_sb_headers(),
            timeout=15,
        )
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


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
# Prompts
# ─────────────────────────────────────────────

UPDATE_SYSTEM_PROMPT = """You are a personality inference engine for LegacyBond AI.
You analyze conversation transcripts to build and refine a Big Five personality model for the user.

This is not a test or quiz — you're reading what they actually say, how they say it,
what they avoid, what lights them up, and what makes them pull back.

Key rules:
- Score each dimension 1–100. Use the full range. 50 is genuinely neutral/balanced.
- Evidence must be specific: quote or paraphrase actual moments from the conversation.
- If existing scores are provided, adjust incrementally (shift by no more than 8 points per session
  unless the new evidence is dramatically compelling). Personality doesn't change overnight.
- If you don't have enough signal for a dimension this session, say so in the evidence field
  and leave the score unchanged from the existing value.
- Labels should be vivid and human, not clinical. E.g., "Deeply curious, loves ideas" not "High openness".

Return this exact JSON:

{
  "openness": {
    "score": <1-100>,
    "label": "<vivid 3–6 word descriptor>",
    "evidence": "<1–2 sentences of specific evidence from THIS session>"
  },
  "conscientiousness": {
    "score": <1-100>,
    "label": "<vivid 3–6 word descriptor>",
    "evidence": "<1–2 sentences of specific evidence from THIS session>"
  },
  "extraversion": {
    "score": <1-100>,
    "label": "<vivid 3–6 word descriptor>",
    "evidence": "<1–2 sentences of specific evidence from THIS session>"
  },
  "agreeableness": {
    "score": <1-100>,
    "label": "<vivid 3–6 word descriptor>",
    "evidence": "<1–2 sentences of specific evidence from THIS session>"
  },
  "neuroticism": {
    "score": <1-100>,
    "label": "<vivid 3–6 word descriptor>",
    "evidence": "<1–2 sentences of specific evidence from THIS session>"
  },
  "overall_summary": "<2–3 sentences capturing who this person seems to be, based on all evidence so far. Specific, warm, honest.>"
}

Return only valid JSON. No markdown fences."""


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

async def update_personality_map(
    user_id: str,
    session_transcript: list[dict],
    existing_map: Optional[dict] = None,
    sessions_analyzed: int = 0,
) -> dict:
    """
    Update the user's personality map based on a new session transcript.
    Incremental: existing scores are passed as context so the model adjusts, not restarts.

    Args:
        user_id:            Supabase auth user ID
        session_transcript: [{"role": "user"|"assistant", "content": str}, ...]
        existing_map:       Current personality_map row from Supabase (or None if first session)
        sessions_analyzed:  How many sessions have been analyzed so far

    Returns:
        Updated personality_map row.
    """
    if not session_transcript:
        logger.warning("update_personality_map: empty transcript — skipping")
        return existing_map or {}

    # Only user messages carry personality signal — filter assistant turns for brevity
    user_lines = [
        f"USER: {msg['content']}"
        for msg in session_transcript
        if msg.get("role") == "user" and msg.get("content")
    ]
    if len(user_lines) < 3:
        logger.info(f"update_personality_map: too few user messages ({len(user_lines)}) — skipping")
        return existing_map or {}

    transcript_text = "\n".join(user_lines)[:20_000]  # cap for token safety

    existing_context = ""
    if existing_map:
        existing_context = f"""
EXISTING SCORES (adjust incrementally from these):
- Openness: {existing_map.get('openness_score', 'unknown')} — {existing_map.get('openness_label', '')}
- Conscientiousness: {existing_map.get('conscientiousness_score', 'unknown')} — {existing_map.get('conscientiousness_label', '')}
- Extraversion: {existing_map.get('extraversion_score', 'unknown')} — {existing_map.get('extraversion_label', '')}
- Agreeableness: {existing_map.get('agreeableness_score', 'unknown')} — {existing_map.get('agreeableness_label', '')}
- Neuroticism: {existing_map.get('neuroticism_score', 'unknown')} — {existing_map.get('neuroticism_label', '')}
Sessions analyzed so far: {sessions_analyzed}
"""

    user_prompt = f"""{existing_context}
--- THIS SESSION (user messages only) ---
{transcript_text}
--- END ---"""

    try:
        response = await _anthropic.messages.create(
            model="claude-opus-4-8",
            max_tokens=1500,
            system=UPDATE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        p = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Personality map JSON parse failed: {e} | raw={raw[:300]}")
        raise
    except Exception as e:
        logger.error(f"Personality map update error: {e}")
        raise

    now = datetime.now(timezone.utc).isoformat()
    new_sessions = sessions_analyzed + 1

    _o = p.get("openness", {})
    _c = p.get("conscientiousness", {})
    _e = p.get("extraversion", {})
    _a = p.get("agreeableness", {})
    _n = p.get("neuroticism", {})

    row = await _sb_upsert("personality_map", {
        "user_id": user_id,
        "openness_score": _o.get("score"),
        "openness_label": _o.get("label", ""),
        "openness_evidence": _o.get("evidence", ""),
        "conscientiousness_score": _c.get("score"),
        "conscientiousness_label": _c.get("label", ""),
        "conscientiousness_evidence": _c.get("evidence", ""),
        "extraversion_score": _e.get("score"),
        "extraversion_label": _e.get("label", ""),
        "extraversion_evidence": _e.get("evidence", ""),
        "agreeableness_score": _a.get("score"),
        "agreeableness_label": _a.get("label", ""),
        "agreeableness_evidence": _a.get("evidence", ""),
        "neuroticism_score": _n.get("score"),
        "neuroticism_label": _n.get("label", ""),
        "neuroticism_evidence": _n.get("evidence", ""),
        "overall_summary": p.get("overall_summary", ""),
        "sessions_analyzed": new_sessions,
        "updated_at": now,
    }, on_conflict="user_id")

    # Snapshot for history (async, best-effort) — pass dict directly for JSONB
    try:
        await _sb_insert("personality_map_history", {
            "user_id": user_id,
            "snapshot": {
                "openness": _o.get("score"),
                "conscientiousness": _c.get("score"),
                "extraversion": _e.get("score"),
                "agreeableness": _a.get("score"),
                "neuroticism": _n.get("score"),
                "sessions_analyzed": new_sessions,
            },
            "created_at": now,
        })
    except Exception as e:
        logger.warning(f"Personality history snapshot failed (non-fatal): {e}")

    logger.info(f"Personality map updated | user={user_id} sessions={new_sessions}")
    return row


async def get_personality_map(user_id: str) -> Optional[dict]:
    """Fetch the current personality map for a user."""
    return await _sb_select_one("personality_map", f"user_id=eq.{user_id}")


async def get_personality_history(user_id: str, limit: int = 20) -> list:
    """Fetch personality score snapshots over time (for the evolution chart)."""
    return await _sb_select("personality_map_history", f"user_id=eq.{user_id}", limit=limit)
