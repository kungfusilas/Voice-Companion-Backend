from fastapi import APIRouter, Depends, HTTPException
from app.routers.auth import verify_token
from app import personality_extractor
from app import personality_tracker

router = APIRouter()

_TIER_RANK: dict[str, int] = {"free": 0, "basic": 1, "premium": 2, "power": 3, "elite": 4}


async def _get_user_tier(user_id: str) -> str:
    import os, httpx
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return "free"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers=headers,
                params={"id": f"eq.{user_id}", "select": "subscription_tier", "limit": "1"},
            )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0].get("subscription_tier", "free") or "free"
    except Exception:
        pass
    return "free"


def _is_power(tier: str) -> bool:
    return _TIER_RANK.get(tier, 0) >= _TIER_RANK["power"]


@router.get("")
async def get_personality_map(user_id: str = Depends(verify_token)):
    tier = await _get_user_tier(user_id)
    if not _is_power(tier):
        raise HTTPException(status_code=403, detail="Power tier required")
    pmap = await personality_extractor._fetch_current_map(user_id)
    return {"personality_map": pmap}


@router.get("/{companion_id}")
async def get_personality_drift(
    companion_id: str,
    user_id: str = Depends(verify_token),
):
    """
    Return a personality drift report for the authenticated user + companion.

    GET /api/personality/{companion_id}

    Compares the oldest and newest of the last 4 Big Five snapshots and reports
    which traits shifted by more than 1.5 points and in which direction.
    """
    drift = await personality_tracker.get_personality_drift(user_id, companion_id)
    return drift
