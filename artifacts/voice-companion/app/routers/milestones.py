"""
Companion Growth System — milestones router.

Endpoints:
  GET  /api/milestones?companion_id=<id>
       Returns bond score, level, all milestone states, and any newly-unlocked
       milestone IDs (unlocked since last seen).

  POST /api/milestones/seen
       Marks a list of milestone IDs as seen (clears the celebration queue).
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth_middleware import verify_token
from app import milestones as ms

logger = logging.getLogger(__name__)
router = APIRouter()


class MarkSeenRequest(BaseModel):
    companion_id: str
    milestone_ids: list[str]


@router.get("")
async def get_milestones(
    companion_id: str = Query(..., description="Companion/persona ID"),
    user_id: str = Depends(verify_token),
) -> dict:
    """
    Returns:
      connection_score  int
      bond_level        str
      milestones        list[MilestoneState]
      newly_unlocked    list[str]  — IDs unlocked since last seen
    """
    try:
        result = await ms.get_milestones(user_id, companion_id)
        return result
    except Exception as exc:
        logger.warning("[milestones] get_milestones error: %r", exc)
        return {
            "connection_score": 50,
            "bond_level": "Warming",
            "milestones": [],
            "newly_unlocked": [],
        }


@router.post("/seen", status_code=200)
async def mark_seen(
    body: MarkSeenRequest,
    user_id: str = Depends(verify_token),
) -> dict:
    """Mark milestone IDs as seen so they won't re-appear in newly_unlocked."""
    try:
        await ms.mark_milestones_seen(user_id, body.companion_id, body.milestone_ids)
    except Exception as exc:
        logger.warning("[milestones] mark_seen error: %r", exc)
    return {"ok": True}
