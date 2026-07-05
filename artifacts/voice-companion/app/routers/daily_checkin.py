"""
Daily check-in router.

The main delivery path is the existing GET /api/proactive-messages endpoint —
daily check-ins are inserted into proactive_messages and picked up automatically.

This router exposes one utility endpoint for manual triggering.  It is
restricted to an admin user (B-H1 fix) to prevent any authenticated user from
firing the job globally and incurring unbounded Claude API costs.

Set the ADMIN_USER_ID environment variable to the Supabase UUID of the admin
account.  Without it, the endpoint returns 403 for everyone.
"""
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.auth_middleware import verify_token
from app import daily_checkin

router = APIRouter()


def _require_admin(user_id: str) -> None:
    """Raise HTTP 403 if user_id does not match the configured admin UUID."""
    admin_id = os.environ.get("ADMIN_USER_ID", "").strip()
    if not admin_id or user_id != admin_id:
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )


@router.post("/trigger")
async def trigger_daily_checkins(
    background_tasks: BackgroundTasks,
    user_id: str = Depends(verify_token),
):
    """
    Manually trigger the daily check-in job for all active users.

    B-H1 fix: restricted to the admin user configured via ADMIN_USER_ID.
    Previously any authenticated user could trigger this, incurring
    unbounded Claude API cost for all users.

    POST /api/daily-checkin/trigger
    """
    _require_admin(user_id)
    background_tasks.add_task(daily_checkin.run_daily_checkins)
    return {
        "status": "triggered",
        "note": "running in background — check proactive messages shortly",
    }
