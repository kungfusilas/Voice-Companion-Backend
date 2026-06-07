"""
Daily check-in router.

The main delivery path is the existing GET /api/proactive-messages endpoint —
daily check-ins are inserted into proactive_messages and picked up automatically.

This router exposes one utility endpoint for manual triggering (useful for
testing without waiting for 9am UTC).
"""
from fastapi import APIRouter, BackgroundTasks

from app import daily_checkin

router = APIRouter()


@router.post("/trigger")
async def trigger_daily_checkins(background_tasks: BackgroundTasks):
    """
    Manually trigger the daily check-in job for all active users.
    Useful for testing — will not double-send because the dedup guard applies.

    POST /api/daily-checkin/trigger
    """
    background_tasks.add_task(daily_checkin.run_daily_checkins)
    return {"status": "triggered", "note": "running in background — check proactive messages shortly"}
