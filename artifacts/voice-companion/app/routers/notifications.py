"""
Notifications router.

  GET /api/notifications/pending-question — return today's daily question for the user
"""
import logging

from fastapi import APIRouter, Depends

from app.auth_middleware import verify_token
from app.services.question_bank import get_daily_question

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/pending-question")
async def pending_question(user_id: str = Depends(verify_token)):
    """
    Return today's daily question for the authenticated user.

    The question is deterministic per (user_id, date) — calling this
    multiple times on the same day always returns the same question.
    The frontend is responsible for showing it only once per session
    (via sessionStorage).
    """
    q = get_daily_question(user_id)
    return q
