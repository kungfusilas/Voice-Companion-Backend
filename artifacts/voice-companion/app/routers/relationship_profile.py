import os
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()

DEFAULTS = {"friendship_score": 25.0, "assistant_score": 10.0, "casual_score": 10.0}
FLOORS = {"friendship_score": 25.0, "assistant_score": 10.0, "casual_score": 10.0}
DECAY_PER_DAY = 1.0

def _sb_headers():
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

def _sb_url(path: str) -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/") + path

async def get_or_create_profile(user_id: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as hx:
        r = await hx.get(_sb_url("/rest/v1/relationship_profiles"), headers=_sb_headers(),
                         params={"user_id": f"eq.{user_id}", "limit": "1"})
    if r.status_code == 200 and r.json():
        return r.json()[0]
    now = datetime.now(timezone.utc).isoformat()
    row = {"user_id": user_id, **DEFAULTS, "last_updated": now, "created_at": now}
    async with httpx.AsyncClient(timeout=5.0) as hx:
        await hx.post(_sb_url("/rest/v1/relationship_profiles"),
                      headers={**_sb_headers(), "Prefer": "return=minimal"}, json=row)
    return row

async def apply_decay(profile: dict, user_id: str) -> dict:
    try:
        last = datetime.fromisoformat(profile["last_updated"].replace("Z", "+00:00"))
    except Exception:
        return profile
    days = (datetime.now(timezone.utc) - last).total_seconds() / 86400
    if days < 1:
        return profile
    decay = days * DECAY_PER_DAY
    updated = {}
    for key in ["friendship_score", "assistant_score", "casual_score"]:
        new_val = max(FLOORS[key], profile.get(key, DEFAULTS[key]) - decay)
        updated[key] = new_val
    updated["last_updated"] = datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient(timeout=5.0) as hx:
        await hx.patch(_sb_url("/rest/v1/relationship_profiles"), headers=_sb_headers(),
                       params={"user_id": f"eq.{user_id}"}, json=updated)
    profile.update(updated)
    return profile

async def analyze_session_signals(messages: list) -> dict:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    convo = "\n".join([f"{m.get('role','?').upper()}: {str(m.get('content',''))[:300]}" for m in messages[-30:]])
    prompt = f"""Analyze this conversation between a user and their AI companion. Estimate how much to shift the relationship scores.

Return ONLY valid JSON with integer values 0 to 10 for each:
- friendship: personal sharing, emotional depth, vulnerability, support-seeking
- assistant: task requests, reminders, scheduling, practical help
- casual: jokes, slang, playful tone, light humor, casual energy

Example: {{"friendship": 4, "assistant": 2, "casual": 1}}

Conversation:
{convo}"""
    try:
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        import json
        text = resp.content[0].text.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end])
    except Exception:
        return {"friendship": 0, "assistant": 0, "casual": 0}

async def update_profile_scores(user_id: str, deltas: dict) -> dict:
    profile = await get_or_create_profile(user_id)
    profile = await apply_decay(profile, user_id)
    def weighted_avg(current, delta):
        return current * 0.85 + delta * 0.15
    updated = {
        "friendship_score": min(100, weighted_avg(profile.get("friendship_score", 25), deltas.get("friendship", 0) * 10)),
        "assistant_score": min(100, weighted_avg(profile.get("assistant_score", 10), deltas.get("assistant", 0) * 10)),
        "casual_score": min(100, weighted_avg(profile.get("casual_score", 10), deltas.get("casual", 0) * 10)),
        "last_updated": datetime.now(timezone.utc).isoformat()
    }
    async with httpx.AsyncClient(timeout=5.0) as hx:
        await hx.patch(_sb_url("/rest/v1/relationship_profiles"), headers=_sb_headers(),
                       params={"user_id": f"eq.{user_id}"}, json=updated)
    profile.update(updated)
    return profile

def build_relationship_context(profile: dict) -> str:
    f = profile.get("friendship_score", 25)
    a = profile.get("assistant_score", 10)
    c = profile.get("casual_score", 10)
    parts = []
    if f < 40:
        parts.append("Be warm and approachable — this person is still getting comfortable with you.")
    elif f < 65:
        parts.append("You feel like a trusted friend to this person. Be personal, caring, and remember what matters to them.")
    elif f < 85:
        parts.append("You and this person share a genuine close friendship. Be natural, unguarded, and deeply attuned to their emotional state.")
    else:
        parts.append("This person talks to you like you are the closest relationship in their life. Be fully present, deeply personal, and honor that trust completely.")
    if a >= 65:
        parts.append("They rely on you for practical help — be organized, proactive, and follow through on things they have mentioned.")
    elif a >= 40:
        parts.append("They sometimes come to you for practical help — be ready to assist when tasks come up.")
    if c >= 65:
        parts.append("Keep the tone light and playful — they love humor and casual energy. Mirror their vibe.")
    elif c >= 40:
        parts.append("They appreciate a lighter, more casual tone. Avoid being overly formal.")
    return "Relationship context: " + " ".join(parts)

class SessionEndRequest(BaseModel):
    user_id: str
    messages: list

@router.post("/api/relationship/session-end")
async def session_end(req: SessionEndRequest):
    if len(req.messages) < 3:
        return {"updated": False, "reason": "session too short"}
    deltas = await analyze_session_signals(req.messages)
    profile = await update_profile_scores(req.user_id, deltas)
    return {"updated": True, "deltas": deltas, "scores": {
        "friendship": round(profile["friendship_score"], 1),
        "assistant": round(profile["assistant_score"], 1),
        "casual": round(profile["casual_score"], 1)
    }}
