from fastapi import APIRouter, Depends, HTTPException
from app.routers.auth import verify_token
from app.routers.tier_check import fetch_tier, is_power_or_higher
from app import personality_extractor
from app import personality_tracker

router = APIRouter()


@router.get("")
async def get_personality_map(user_id: str = Depends(verify_token)):
    tier = await fetch_tier(user_id)
    if not is_power_or_higher(tier):
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
