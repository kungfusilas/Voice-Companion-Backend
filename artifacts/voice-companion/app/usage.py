"""
Usage metering helpers for BondAI.

Public surface:
  get_user_tier(user_id)                          → (tier, status)
  check_message_quota(user_id, tier, session_id)  → None | raises 402/429/401
  check_voice_quota(user_id, tier, secs, sid)     → None | raises 402/429/401
  register_session(user_id, session_id)           → None
  get_usage_status(user_id, tier)                 → dict
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import httpx

from fastapi import HTTPException

from app.usage_config import ALLOWANCES, HOURLY_CAPS, TOPUP_PACKS

logger = logging.getLogger(__name__)


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _supa_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _supa_headers() -> dict[str, str]:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


# ── Profile lookup (shared across routers) ───────────────────────────────────

async def get_user_tier(user_id: str) -> tuple[str, str]:
    """Return (subscription_tier, subscription_status) for an authenticated user."""
    url = _supa_url()
    if not url:
        return ("free", "inactive")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers=_supa_headers(),
                params={
                    "id": f"eq.{user_id}",
                    "select": "subscription_tier,subscription_status",
                    "limit": "1",
                },
            )
        if resp.status_code == 200 and resp.json():
            row = resp.json()[0]
            return (
                row.get("subscription_tier", "free"),
                row.get("subscription_status", "inactive"),
            )
    except Exception as exc:
        logger.warning("get_user_tier fallback for uid=%s: %s", user_id[:8], exc)
    return ("free", "inactive")


# ── Pack helpers ──────────────────────────────────────────────────────────────

def _packs_for_kind(kind: str) -> list[dict]:
    """Return relevant top-up packs for a quota kind label (messages / voice)."""
    pack_kind = "msgs" if kind == "messages" else "voice_secs"
    return [
        {
            "key": k,
            "name": v["name"],
            "price": f"${v['amount'] / 100:.2f}",
            "credits": v["credits"],
        }
        for k, v in TOPUP_PACKS.items()
        if v["kind"] == pack_kind
    ]


# ── Core atomic-quota call ────────────────────────────────────────────────────

async def _call_consume_quota(
    user_id: str,
    kind: str,
    amount: int,
    allowance: int,
    session_id: str | None,
) -> dict:
    """
    Call the consume_quota Postgres RPC.
    On any DB error we fail open so a transient outage does not block users.
    """
    url = _supa_url()
    if not url:
        return {"ok": True}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{url}/rest/v1/rpc/consume_quota",
                headers=_supa_headers(),
                json={
                    "p_user_id": user_id,
                    "p_kind": kind,
                    "p_amount": amount,
                    "p_allowance": allowance,
                    "p_session_id": session_id or "",
                    "p_hourly_msg_cap": HOURLY_CAPS["msgs"],
                    "p_hourly_voice_cap": HOURLY_CAPS["voice_secs"],
                },
            )
        if resp.status_code != 200:
            return {"ok": True, "_rpc_err": resp.text[:200]}
        return resp.json()
    except Exception:
        return {"ok": True, "_rpc_err": "timeout"}


def _raise_for_quota_result(result: dict, kind_label: str) -> None:
    error = result.get("error", "")
    if error == "hourly_cap":
        raise HTTPException(
            status_code=429,
            detail={
                "code": "hourly_cap",
                "kind": result.get("kind", kind_label),
                "message": "Hourly limit reached — please try again in a few minutes.",
            },
        )
    if error == "quota_exceeded":
        raise HTTPException(
            status_code=402,
            detail={
                "code": "quota_exceeded",
                "kind": result.get("kind", kind_label),
                "renews_at": result.get("renews_at"),
                "packs": _packs_for_kind(result.get("kind", kind_label)),
            },
        )


# ── Public quota-check functions ──────────────────────────────────────────────

async def check_message_quota(
    user_id: str,
    tier: str,
    session_id: str | None,
) -> None:
    """Deduct 1 message. Raises 402/429/401 on failure."""
    allowance = ALLOWANCES.get(tier, ALLOWANCES["free"])["msgs"]
    result = await _call_consume_quota(user_id, "message", 1, allowance, session_id)
    if not result.get("ok"):
        _raise_for_quota_result(result, "messages")


async def check_voice_quota(
    user_id: str,
    tier: str,
    seconds: int,
    session_id: str | None,
) -> None:
    """Deduct voice seconds. Raises 402/429/401 on failure."""
    allowance = ALLOWANCES.get(tier, ALLOWANCES["free"])["voice_secs"]
    if allowance == 0:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "quota_exceeded",
                "kind": "voice",
                "renews_at": None,
                "packs": _packs_for_kind("voice"),
            },
        )
    result = await _call_consume_quota(user_id, "voice", seconds, allowance, session_id)
    if not result.get("ok"):
        _raise_for_quota_result(result, "voice")


# ── Session registration ──────────────────────────────────────────────────────

async def register_session(user_id: str, session_id: str) -> None:
    """No-op — multi-device sessions are allowed; no session enforcement."""
    pass


# ── Usage status ──────────────────────────────────────────────────────────────

async def get_usage_status(user_id: str, tier: str) -> dict:
    """Return current monthly usage for a user."""
    allowances = ALLOWANCES.get(tier, ALLOWANCES["free"])
    empty: dict = {
        "msgs_used": 0,
        "msgs_allowance": allowances["msgs"],
        "topup_msgs": 0,
        "voice_seconds_used": 0,
        "voice_allowance": allowances["voice_secs"],
        "topup_voice_seconds": 0,
        "usage_period_start": None,
        "renews_at": None,
    }
    url = _supa_url()
    if not url:
        return empty
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers=_supa_headers(),
                params={
                    "id": f"eq.{user_id}",
                    "select": "msgs_used,voice_seconds_used,topup_msgs,topup_voice_seconds,usage_period_start",
                    "limit": "1",
                },
            )
        if resp.status_code == 200 and resp.json():
            row = resp.json()[0]
            period_start = row.get("usage_period_start")
            renews_at = None
            if period_start:
                try:
                    start = datetime.fromisoformat(period_start.replace("Z", "+00:00"))
                    renews_at = (start + timedelta(days=30)).isoformat()
                except Exception:
                    pass
            return {
                "msgs_used": row.get("msgs_used") or 0,
                "msgs_allowance": allowances["msgs"],
                "topup_msgs": row.get("topup_msgs") or 0,
                "voice_seconds_used": row.get("voice_seconds_used") or 0,
                "voice_allowance": allowances["voice_secs"],
                "topup_voice_seconds": row.get("topup_voice_seconds") or 0,
                "usage_period_start": period_start,
                "renews_at": renews_at,
            }
    except Exception:
        pass
    return empty
