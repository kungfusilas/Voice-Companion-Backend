"""
Waitlist router — no auth required.

POST /api/waitlist  { email, companion_id? }  → { success: true }

Inserts into the `waitlist` Supabase table via service role.
Duplicate (email, companion_id) entries are silently ignored.
"""
import os
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class WaitlistRequest(BaseModel):
    email: str
    companion_id: str | None = None
    user_id: str | None = None


@router.post("")
async def join_waitlist(req: WaitlistRequest):
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not supabase_url or not service_key:
        raise HTTPException(500, "Supabase not configured")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{supabase_url}/rest/v1/waitlist",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=ignore-duplicates,return=minimal",
            },
            json={
                "email": req.email.strip().lower(),
                "companion_id": req.companion_id,
                "user_id": req.user_id,
            },
        )

    if resp.status_code not in (200, 201):
        raise HTTPException(resp.status_code, "Could not join waitlist")

    return {"success": True}
