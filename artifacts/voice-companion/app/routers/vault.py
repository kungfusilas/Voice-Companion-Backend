import os
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional
import anthropic
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.routers.auth import verify_token
from app.auth_middleware import verify_token_or_guest

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
async def save_session(body: SaveSessionRequest, token_user_id: str = Depends(verify_token_or_guest)):
    if not body.user_id or not body.messages:
        raise HTTPException(400, "user_id and messages required")
    if body.user_id != token_user_id:
        raise HTTPException(403, "user_id does not match authenticated user")

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

    async def _rel_bg():
        try:
            from app.routers.relationship_profile import analyze_session_signals, update_profile_scores
            msgs = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in body.messages] if body.messages else []
            if len(msgs) >= 3:
                deltas = await analyze_session_signals(msgs)
                await update_profile_scores(body.user_id, deltas)
        except Exception:
            pass
    asyncio.create_task(_rel_bg())
    return {"id": row.get("id"), "title": title}


# ── List sessions ─────────────────────────────────────────────────────────────

@router.get("/api/vault/sessions")
async def list_sessions(user_id: str = Depends(verify_token)):
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
async def get_session(session_id: str, user_id: str = Depends(verify_token)):
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
async def delete_session(session_id: str, user_id: str = Depends(verify_token)):
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
async def upsert_recipient(body: RecipientRequest, token_user_id: str = Depends(verify_token)):
    if body.user_id != token_user_id:
        raise HTTPException(403, "Forbidden")
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
async def get_recipient(user_id: str = Depends(verify_token)):
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


# ── Vault photo files ─────────────────────────────────────────────────────────

@router.post("/api/vault/upload-photo")
async def upload_photo(body: dict, token_user_id: str = Depends(verify_token)):
    import uuid as _uuid, base64 as _b64
    user_id = body.get("user_id", "")
    image_base64 = body.get("image_base64", "")
    filename = body.get("filename", "photo.jpg")
    if not user_id or not image_base64:
        raise HTTPException(status_code=400, detail="user_id and image_base64 required")
    if token_user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]
    try:
        image_bytes = _b64.b64decode(image_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 data")
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large (max 10MB)")
    file_id = str(_uuid.uuid4())
    storage_path = f"vault/{user_id}/{file_id}.jpg"
    supabase_url = os.environ.get("SUPABASE_URL", "")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    async with httpx.AsyncClient() as client:
        up = await client.post(
            f"{supabase_url}/storage/v1/object/vault-files/{storage_path}",
            content=image_bytes,
            headers={"Authorization": f"Bearer {service_key}", "Content-Type": "image/jpeg", "x-upsert": "true"},
            timeout=20.0,
        )
        if up.status_code not in (200, 201):
            raise HTTPException(status_code=500, detail=f"Storage error: {up.text}")
        public_url = f"{supabase_url}/storage/v1/object/public/vault-files/{storage_path}"
        await client.post(
            f"{supabase_url}/rest/v1/vault_files",
            json={"id": file_id, "user_id": user_id, "storage_path": storage_path, "url": public_url, "filename": filename, "size_bytes": len(image_bytes)},
            headers={**_sb_headers(), "Content-Type": "application/json"},
            timeout=10.0,
        )
    return {"file_id": file_id, "url": public_url, "path": storage_path}


@router.get("/api/vault/files")
async def list_files(user_id: str, token_user_id: str = Depends(verify_token)):
    if token_user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{os.environ.get('SUPABASE_URL','')}/rest/v1/vault_files",
            params={"user_id": f"eq.{user_id}", "order": "uploaded_at.desc", "limit": "200"},
            headers=_sb_headers(),
            timeout=10.0,
        )
    return {"files": resp.json() if resp.status_code == 200 else []}
