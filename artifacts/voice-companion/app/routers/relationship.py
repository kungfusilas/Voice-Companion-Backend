"""
Relationship stats and type endpoints.

Available to all authenticated users — relationship depth emerges naturally
through conversation across all paid tiers. Not tier-gated.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app import relationship
from app.auth_middleware import verify_token

router = APIRouter()


class SetTypeRequest(BaseModel):
    user_id: str
    companion_id: str
    relationship_type: str  # romance | mentor | friendship | professional


@router.post("/type")
async def set_relationship_type(
    req: SetTypeRequest,
    _: str = Depends(verify_token),
):
    """Save the chosen relationship type for a user+companion pair."""
    await relationship.upsert_relationship_type(
        req.user_id, req.companion_id, req.relationship_type
    )
    return {"ok": True}


@router.get("/{user_id}/{companion_id}")
async def get_relationship(
    user_id: str,
    companion_id: str,
    _: str = Depends(verify_token),
):
    """Return the current relationship stats for a user+companion pair."""
    stats = await relationship.get_stats(user_id, companion_id)
    return stats
