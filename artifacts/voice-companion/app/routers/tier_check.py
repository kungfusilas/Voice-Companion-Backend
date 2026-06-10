"""
Shared tier-gating helpers.

Usage:
    from app.routers.tier_check import require_premium

    @router.post("/something")
    async def my_endpoint(user_id: str = Depends(verify_token)):
        await require_premium(user_id)
        ...
"""
from __future__ import annotations

import os

import httpx
from fastapi import HTTPException

_TIER_RANK: dict[str, int] = {
    "free": 0,
    "basic": 1,
    "premium": 2,
    "power": 3,
    "elite": 4,
}

_403_DETAIL = {
    "code": "plan_required",
    "required": "premium",
    "message": (
        "This feature requires a Premium plan or higher. "
        "Upgrade in Settings → Pricing."
    ),
}


def _supa_headers() -> dict[str, str]:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def fetch_tier(user_id: str) -> str:
    """Return the subscription_tier for a user (defaults to 'free' on any error)."""
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
                    "select": "subscription_tier",
                    "limit": "1",
                },
            )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0].get("subscription_tier", "free") or "free"
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
        raise HTTPException(status_code=403, detail=_403_DETAIL)


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
