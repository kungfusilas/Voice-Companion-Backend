"""
Push notification router.

  GET  /api/push/vapid-public-key  — return VAPID public key (no auth needed)
  POST /api/push/subscribe         — save a push subscription for the caller
  DELETE /api/push/unsubscribe     — remove the caller's push subscription

Database table required in Supabase (run once in SQL Editor):
─────────────────────────────────────────────────────────────
  CREATE TABLE IF NOT EXISTS push_subscriptions (
    id         bigserial PRIMARY KEY,
    user_id    uuid        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    endpoint   text        NOT NULL UNIQUE,
    p256dh     text        NOT NULL,
    auth       text        NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
  );

  ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;

  CREATE POLICY "Users manage own subscriptions"
    ON push_subscriptions
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
─────────────────────────────────────────────────────────────
"""
import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth_middleware import verify_token

logger = logging.getLogger(__name__)
router = APIRouter()


# ── helpers ─────────────────────────────────────────────────────────────────

def _supabase_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _supabase_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_KEY not configured")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


# ── models ───────────────────────────────────────────────────────────────────

class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscribeRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys


# ── routes ───────────────────────────────────────────────────────────────────

@router.get("/vapid-public-key")
async def get_vapid_public_key():
    """Return the VAPID public key so the frontend can subscribe."""
    public_key = os.environ.get("VAPID_PUBLIC_KEY", "")
    if not public_key:
        raise HTTPException(status_code=503, detail="Push notifications not configured")
    return {"publicKey": public_key}


@router.post("/subscribe", status_code=201)
async def subscribe(body: PushSubscribeRequest, user_id: str = Depends(verify_token)):
    """Save or refresh a push subscription for the authenticated user."""
    url = _supabase_url()
    headers = _supabase_headers()

    payload = {
        "user_id": user_id,
        "endpoint": body.endpoint,
        "p256dh": body.keys.p256dh,
        "auth": body.keys.auth,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Upsert by endpoint — one row per browser/device
        resp = await client.post(
            f"{url}/rest/v1/push_subscriptions",
            json=payload,
            headers={
                **headers,
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
        )

    if resp.status_code not in (200, 201):
        logger.error("push subscribe DB error %s: %s", resp.status_code, resp.text)
        raise HTTPException(status_code=500, detail="Failed to save subscription")

    logger.info("push subscription saved user=%s", user_id)
    return {"ok": True}


@router.delete("/unsubscribe")
async def unsubscribe(body: PushSubscribeRequest, user_id: str = Depends(verify_token)):
    """Remove a push subscription for the authenticated user."""
    url = _supabase_url()
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(
            f"{url}/rest/v1/push_subscriptions",
            params={"user_id": f"eq.{user_id}", "endpoint": f"eq.{body.endpoint}"},
            headers=headers,
        )

    if resp.status_code not in (200, 204):
        logger.error("push unsubscribe DB error %s: %s", resp.status_code, resp.text)
        raise HTTPException(status_code=500, detail="Failed to remove subscription")

    return {"ok": True}
