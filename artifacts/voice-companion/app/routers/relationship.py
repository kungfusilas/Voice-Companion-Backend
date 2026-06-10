from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app import relationship
from app.auth_middleware import verify_token
from app.routers.tier_check import require_premium

router = APIRouter()


class SetTypeRequest(BaseModel):
    user_id: str
    companion_id: str
    relationship_type: str  # romance | mentor | friendship | professional


@router.post("/type")
async def set_relationship_type(
    req: SetTypeRequest,
    auth_user_id: str = Depends(verify_token),
):
    """Save the chosen relationship type for a user+companion pair. Premium+."""
    await require_premium(auth_user_id)
    await relationship.upsert_relationship_type(
        req.user_id, req.companion_id, req.relationship_type
    )
    return {"ok": True}


@router.get("/{user_id}/{companion_id}")
async def get_relationship(
    user_id: str,
    companion_id: str,
    auth_user_id: str = Depends(verify_token),
):
    """Return the current relationship stats for a user+companion pair. Premium+."""
    await require_premium(auth_user_id)
    stats = await relationship.get_stats(user_id, companion_id)
    return stats
