"""
Shared tier-gating helpers.

fetch_tier() is the single canonical source of truth for a user's effective
subscription tier.  It reads BOTH subscription_tier AND access_expires_at from
the profiles table and enforces the expiry:

  • If access_expires_at is set and is in the past → return "free"
  • If access_expires_at cannot be parsed → fail-open (return tier as-is so a
    paying user is never locked out by a malformed date)
  • On any network / DB error → return "free" (safe default)

All tier-gating helpers (require_paid / require_premium / require_power) and
every file that previously had its own _get_tier / _get_user_tier helper
MUST import and call this function instead of duplicating the logic.

Usage:
    from app.routers.tier_check import require_premium, fetch_tier

    @router.post("/something")
    async def my_endpoint(user_id: str = Depends(verify_token)):
        await require_premium(user_id)
        ...
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException

_TIER_RANK: dict[str, int] = {
    "free": 0,
    "basic": 1,
    "premium": 2,
    "power": 3,
    "elite": 4,
}


def _supa_headers() -> dict[str, str]:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def fetch_tier(user_id: str) -> str:
    """Return the effective subscription tier for a user.

    Enforces access_expires_at: if the expiry timestamp is set and is in the
    past the user is treated as free regardless of subscription_tier.
    Fails open on unparseable dates so a paying user is never locked out.
    Returns "free" on any network or DB error.
    """
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return "free"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers=_supa_headers(),
                params={
                    "id": f"eq.{user_id}",
                    "select": "subscription_tier,access_expires_at",
                    "limit": "1",
                },
            )
        if resp.status_code == 200 and resp.json():
            row = resp.json()[0]
            tier = row.get("subscription_tier") or "free"
            expires_raw = row.get("access_expires_at")
            if expires_raw:
                try:
                    expires_dt = datetime.fromisoformat(
                        expires_raw.replace("Z", "+00:00")
                    )
                    if expires_dt < datetime.now(timezone.utc):
                        return "free"
                except Exception:
                    pass  # fail-open: unparseable date → keep tier
            return tier
    except Exception:
        pass
    return "free"


def is_premium_or_higher(tier: str) -> bool:
    return _TIER_RANK.get(tier, 0) >= _TIER_RANK["premium"]


def is_power_or_higher(tier: str) -> bool:
    return _TIER_RANK.get(tier, 0) >= _TIER_RANK["power"]


def is_paid(tier: str) -> bool:
    return _TIER_RANK.get(tier, 0) >= _TIER_RANK["basic"]


async def require_premium(user_id: str) -> None:
    """Raise HTTP 403 if the authenticated user is below Premium tier."""
    tier = await fetch_tier(user_id)
    if not is_premium_or_higher(tier):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "plan_required",
                "required": "premium",
                "message": (
                    "This feature requires a Premium plan or higher. "
                    "Upgrade in Settings → Pricing."
                ),
            },
        )


async def require_power(user_id: str) -> None:
    """Raise HTTP 403 if the authenticated user is below Power tier."""
    tier = await fetch_tier(user_id)
    if not is_power_or_higher(tier):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "plan_required",
                "required": "power",
                "message": (
                    "This feature requires a Power plan. "
                    "Upgrade in Settings → Pricing."
                ),
            },
        )


async def require_paid(user_id: str) -> None:
    """Raise HTTP 403 if the user is on the free tier (no active subscription)."""
    tier = await fetch_tier(user_id)
    if not is_paid(tier):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "plan_required",
                "required": "basic",
                "message": (
                    "This feature requires an active subscription. "
                    "Upgrade in Settings → Pricing."
                ),
            },
        )
