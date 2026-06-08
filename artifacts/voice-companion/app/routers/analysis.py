"""
Deep Communication Analysis — Power tier.

POST /api/analysis/debrief  — triggered by the frontend when user leaves chat.
GET  /api/analysis/debriefs — returns recent debriefs for the user (Hub display).

Supabase: run once in SQL editor:
    create table if not exists conversation_debriefs (
      id           uuid primary key default gen_random_uuid(),
      user_id      text not null,
      session_id   text not null,
      companion_id text,
      created_at   timestamptz not null default now(),
      debrief      jsonb not null default '{}'::jsonb
    );
    create index if not exists debriefs_user_idx on conversation_debriefs (user_id, created_at desc);
"""

import os
import json
import logging
import httpx
import anthropic
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.routers.auth import verify_token
from app import store

logger = logging.getLogger(__name__)
router = APIRouter()

_HAIKU = "claude-haiku-4-5-20251001"
_TIER_RANK: dict[str, int] = {"free": 0, "basic": 1, "premium": 2, "power": 3, "elite": 4}


def _supa_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def _get_tier(user_id: str) -> str:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return "free"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers=_supa_headers(),
                params={"id": f"eq.{user_id}", "select": "subscription_tier", "limit": "1"},
            )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0].get("subscription_tier", "free") or "free"
    except Exception:
        pass
    return "free"


def _is_power(tier: str) -> bool:
    return _TIER_RANK.get(tier, 0) >= _TIER_RANK["power"]


class DebriefRequest(BaseModel):
    session_id: str
    companion_id: str | None = None
    companion_name: str | None = None


async def _run_analysis(
    user_id: str,
    session_id: str,
    companion_id: str | None,
    companion_name: str | None,
) -> dict:
    history = store.get_history(session_id)
    if not history or len([m for m in history if m.role == "user"]) < 3:
        raise ValueError("Not enough conversation to analyze")

    # Build transcript snippet (last 40 messages max to stay within token limits)
    recent = history[-40:]
    transcript_lines = []
    for m in recent:
        role = "User" if m.role == "user" else f"Companion ({companion_name or 'AI'})"
        transcript_lines.append(f"{role}: {m.content[:300]}")
    transcript = "\n".join(transcript_lines)

    prompt = f"""Analyze the behavioral patterns in this conversation transcript. 
Focus on what the USER reveals about their communication style.

TRANSCRIPT:
{transcript}

Return a JSON object with exactly these fields:
{{
  "metrics": {{
    "negative_self_talk": <integer count of times user used negative self-talk about themselves>,
    "deflected_questions": <integer count of times user deflected or avoided a direct question>,
    "opened_up_moments": <integer count of times user showed genuine vulnerability or openness>,
    "humor_as_deflection": <integer count of times user used humor to deflect something emotional>,
    "emotional_openness_score": <integer 1-10, where 10 is fully open>
  }},
  "patterns": [<3-4 short behavioral pattern observations, e.g. "You followed most vulnerable moments with a joke">],
  "companion_note": "<1-2 sentences from the companion's perspective — warm, not clinical>",
  "highlight": "<one standout positive moment from the conversation, 1 sentence>"
}}

Rules:
- Base counts ONLY on what is clearly present in the transcript. Use 0 if not present.
- Patterns should be specific and behavioral, not generic.
- Companion note should be warm and encouraging, not clinical.
- Return ONLY valid JSON."""

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    msg = client.messages.create(
        model=_HAIKU,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    analysis = json.loads(msg.content[0].text)
    analysis["session_id"] = session_id
    analysis["companion_name"] = companion_name
    analysis["message_count"] = len([m for m in history if m.role == "user"])
    analysis["created_at"] = datetime.now(timezone.utc).isoformat()
    return analysis


async def _save_debrief(user_id: str, session_id: str, companion_id: str | None, debrief: dict) -> None:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return
    headers = {**_supa_headers(), "Prefer": "return=minimal"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            await client.post(
                f"{url}/rest/v1/conversation_debriefs",
                headers=headers,
                json={
                    "user_id": user_id,
                    "session_id": session_id,
                    "companion_id": companion_id,
                    "debrief": debrief,
                },
            )
    except Exception as e:
        logger.debug("Save debrief failed: %s", e)


@router.post("/debrief")
async def create_debrief(body: DebriefRequest, user_id: str = Depends(verify_token)):
    tier = await _get_tier(user_id)
    if not _is_power(tier):
        raise HTTPException(status_code=403, detail="Power tier required")
    try:
        debrief = await _run_analysis(user_id, body.session_id, body.companion_id, body.companion_name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await _save_debrief(user_id, body.session_id, body.companion_id, debrief)
    return {"debrief": debrief}


@router.get("/debriefs")
async def list_debriefs(limit: int = 10, user_id: str = Depends(verify_token)):
    tier = await _get_tier(user_id)
    if not _is_power(tier):
        raise HTTPException(status_code=403, detail="Power tier required")
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return {"debriefs": []}
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/conversation_debriefs",
                headers=_supa_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "select": "id,created_at,companion_id,debrief",
                    "order": "created_at.desc",
                    "limit": str(min(limit, 20)),
                },
            )
        if resp.status_code == 200:
            return {"debriefs": resp.json()}
    except Exception as e:
        logger.debug("List debriefs failed: %s", e)
    return {"debriefs": []}
