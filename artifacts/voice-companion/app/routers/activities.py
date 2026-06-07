"""
Activity endpoints.
POST /api/activity         — generate a new activity
POST /api/activity/result  — save a completed activity result
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app import activities as act_core

router = APIRouter()


class ActivityRequest(BaseModel):
    companion_id: str
    user_id: str
    activity_type: str  # word_game | trivia | would_you_rather


class ActivityResultRequest(BaseModel):
    user_id: str
    companion_id: str
    activity_type: str
    result: str  # won | lost | completed


@router.post("")
async def start_activity(req: ActivityRequest):
    """Generate a new activity and return its data."""
    try:
        data = await act_core.generate_activity(req.companion_id, req.activity_type)
        return data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Activity generation failed: {e}")


@router.post("/result")
async def save_activity_result(req: ActivityResultRequest):
    """Persist an activity result for streak tracking."""
    try:
        from app.relationship import _get_client as _get_db
        db = _get_db()
        db.table("activity_results").insert({
            "user_id": req.user_id,
            "companion_id": req.companion_id,
            "activity_type": req.activity_type,
            "result": req.result,
        }).execute()
        return {"ok": True}
    except Exception:
        return {"ok": False}
