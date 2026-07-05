"""
Activity endpoints.
POST /api/activity         — generate a new activity
POST /api/activity/result  — save a completed activity result

Available to all paid tiers (Basic, Premium, Power).
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app import activities as act_core
from app.auth_middleware import verify_token
from app.routers.tier_check import require_paid

logger = logging.getLogger(__name__)
router = APIRouter()


class ActivityRequest(BaseModel):
    companion_id: str
    activity_type: str  # word_game | trivia | would_you_rather


class ActivityResultRequest(BaseModel):
    companion_id: str
    activity_type: str
    result: str  # won | lost | completed


@router.post("")
async def start_activity(
    req: ActivityRequest,
    auth_user_id: str = Depends(verify_token),
):
    """Generate a new activity and return its data. Requires any paid plan."""
    await require_paid(auth_user_id)
    try:
        data = await act_core.generate_activity(req.companion_id, req.activity_type)
        return data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Activity generation failed: {e}")


@router.post("/result")
async def save_activity_result(
    req: ActivityResultRequest,
    auth_user_id: str = Depends(verify_token),
):
    """Persist an activity result for streak tracking. Requires any paid plan.

    B-C1 fix: user_id removed from request body — always uses the JWT-verified
    auth_user_id so a caller cannot write results to another user's account.
    A-C1b fix: DB insert wrapped in asyncio.to_thread to avoid blocking the
    event loop (supabase-py client is synchronous).
    """
    await require_paid(auth_user_id)
    try:
        from app.relationship import _get_client as _get_db
        db = _get_db()
        await asyncio.to_thread(
            lambda: db.table("activity_results").insert({
                "user_id": auth_user_id,
                "companion_id": req.companion_id,
                "activity_type": req.activity_type,
                "result": req.result,
            }).execute()
        )
        return {"ok": True}
    except Exception:
        logger.debug("save_activity_result: DB insert failed", exc_info=True)
        return {"ok": False}
