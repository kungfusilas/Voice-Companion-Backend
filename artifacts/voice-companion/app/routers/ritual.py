"""
Weekly Relationship-Building Ritual — router.

Endpoints:
  GET /api/ritual/status?companion_id=<id>
      Returns {due: bool, questions: list[str] | null}.
      When due=True, a session row is recorded immediately (7-day cooldown starts).
      Fails gracefully — if the table doesn't exist yet, returns {due: false}.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Query

from app.auth_middleware import verify_token
from app import ritual as ritual_svc

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/status")
async def ritual_status(
    companion_id: str = Query(..., description="Companion/persona ID"),
    user_id: str = Depends(verify_token),
) -> dict:
    """
    Returns:
      due        bool
      questions  list[str] | null  — selected questions (only when due=True)
    """
    result = await ritual_svc.check_ritual_due(user_id, companion_id)
    return result
