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
    companion_id: str
    relationship_type: str  # romance | mentor | friendship | professional
    # user_id intentionally omitted — derived from the verified JWT below


@router.post("/type")
async def set_relationship_type(
    req: SetTypeRequest,
    user_id: str = Depends(verify_token),
):
    """Save the chosen relationship type for the authenticated user+companion pair."""
    await relationship.upsert_relationship_type(
        user_id, req.companion_id, req.relationship_type
    )
    return {"ok": True}


@router.get("/{user_id}/{companion_id}")
async def get_relationship(
    user_id: str,
    companion_id: str,
    auth_user_id: str = Depends(verify_token),
):
    """Return the current relationship stats for the authenticated user+companion pair.

    The path {user_id} is accepted for URL compatibility but the response always
    reflects the authenticated user's data — a user can never read another user's stats.
    """
    stats = await relationship.get_stats(auth_user_id, companion_id)
    return stats
