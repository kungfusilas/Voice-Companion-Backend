import os
import json
from datetime import datetime, timezone
from typing import Optional
import anthropic
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


def _sb_headers():
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _sb_url(path: str) -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/") + path


# ── Save session ──────────────────────────────────────────────────────────────

class SaveSessionRequest(BaseModel):
    user_id: str
    messages: list[dict]


@router.post("/api/vault/save-session")
async def save_session(body: SaveSessionRequest):
    if not body.user_id or not body.messages:
        raise HTTPException(400, "user_id and messages required")

    recent = body.messages[-40:]
    convo_text = "\n".join(
        f"{m.get('role','').upper()}: {str(m.get('content',''))[:300]}"
        for m in recent
        if str(m.get("content", "")).strip()
    )

    ai = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    msg = await ai.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=60,
        messages=[{
            "role": "user",
            "content": (
                "Generate a short, meaningful title (5-8 words) that captures "
                "the emotional core or main topic of this conversation. "
                "No dates, no companion names. Focus on what this was really about for the person. "
                "Return only the title text, nothing else.\n\n"
                f"Conversation:\n{convo_text}"
            )
        }]
    )
    raw_title = msg.content[0].text.strip().strip('"').strip("'")

    today = datetime.now(timezone.utc)
    date_str = today.strftime("%B %-d, %Y")
    title = f"{raw_title} · {date_str}"

    async with httpx.AsyncClient(timeout=10.0) as hx:
        r = await hx.post(
            _sb_url("/rest/v1/vault_sessions"),
            headers={**_sb_headers(), "Prefer": "return=representation"},
            json={
                "user_id": body.user_id,
                "title": title,
                "messages": body.messages,
                "message_count": len(body.messages),
            }
        )
    if r.status_code not in (200, 201):
        raise HTTPException(500, f"Save failed: {r.text}")

    saved = r.json()
    row = saved[0] if isinstance(saved, list) else saved

    # Update the adaptive relationship profile from this session (best-effort).
    try:
        from app.routers.relationship_profile import analyze_session_signals, update_profile_scores
        messages_for_analysis = [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in body.messages
        ] if body.messages else []
        if len(messages_for_analysis) >= 3:
            deltas = await analyze_session_signals(messages_for_analysis)
            await update_profile_scores(body.user_id, deltas)
    except Exception:
        pass

    return {"id": row.get("id"), "title": title}


# ── List sessions ─────────────────────────────────────────────────────────────

@router.get("/api/vault/sessions")
async def list_sessions(user_id: str):
    async with httpx.AsyncClient(timeout=10.0) as hx:
        r = await hx.get(
            _sb_url("/rest/v1/vault_sessions"),
            headers=_sb_headers(),
            params={
                "user_id": f"eq.{user_id}",
                "select": "id,title,message_count,created_at",
                "order": "created_at.desc",
                "limit": "100",
            }
        )
    if r.status_code != 200:
        raise HTTPException(500, r.text)
    return r.json()


# ── Get single session (for download) ────────────────────────────────────────

@router.get("/api/vault/sessions/{session_id}")
async def get_session(session_id: str, user_id: str):
    async with httpx.AsyncClient(timeout=10.0) as hx:
        r = await hx.get(
            _sb_url(f"/rest/v1/vault_sessions"),
            headers=_sb_headers(),
            params={"id": f"eq.{session_id}", "user_id": f"eq.{user_id}", "limit": "1"}
        )
    if r.status_code != 200:
        raise HTTPException(500, r.text)
    data = r.json()
    if not data:
        raise HTTPException(404, "Session not found")
    return data[0]


# ── Delete session ────────────────────────────────────────────────────────────

@router.delete("/api/vault/sessions/{session_id}")
async def delete_session(session_id: str, user_id: str):
    async with httpx.AsyncClient(timeout=10.0) as hx:
        r = await hx.delete(
            _sb_url("/rest/v1/vault_sessions"),
            headers=_sb_headers(),
            params={"id": f"eq.{session_id}", "user_id": f"eq.{user_id}"}
        )
    if r.status_code not in (200, 204):
        raise HTTPException(500, r.text)
    return {"deleted": True}


# ── Legacy recipient ──────────────────────────────────────────────────────────

class RecipientRequest(BaseModel):
    user_id: str
    name: str
    email: str
    relationship: Optional[str] = None
    personal_message: Optional[str] = None
    inactivity_days: int = 365


@router.post("/api/vault/recipient")
async def upsert_recipient(body: RecipientRequest):
    async with httpx.AsyncClient(timeout=10.0) as hx:
        r = await hx.post(
            _sb_url("/rest/v1/legacy_recipients"),
            headers={**_sb_headers(), "Prefer": "resolution=merge-duplicates,return=representation"},
            params={"on_conflict": "user_id"},
            json={
                "user_id": body.user_id,
                "name": body.name,
                "email": body.email,
                "relationship": body.relationship,
                "personal_message": body.personal_message,
                "inactivity_days": body.inactivity_days,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    if r.status_code not in (200, 201):
        raise HTTPException(500, r.text)
    data = r.json()
    return data[0] if isinstance(data, list) else data


@router.get("/api/vault/recipient")
async def get_recipient(user_id: str):
    async with httpx.AsyncClient(timeout=10.0) as hx:
        r = await hx.get(
            _sb_url("/rest/v1/legacy_recipients"),
            headers=_sb_headers(),
            params={"user_id": f"eq.{user_id}", "limit": "1"}
        )
    if r.status_code != 200:
        raise HTTPException(500, r.text)
    data = r.json()
    return data[0] if data else None
