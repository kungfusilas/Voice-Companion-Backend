from fastapi import APIRouter
from pydantic import BaseModel
from app import relationship

router = APIRouter()


class SetTypeRequest(BaseModel):
    user_id: str
    companion_id: str
    relationship_type: str  # romance | mentor | friendship | professional


@router.post("/type")
async def set_relationship_type(req: SetTypeRequest):
    """Save the chosen relationship type for a user+companion pair."""
    await relationship.upsert_relationship_type(req.user_id, req.companion_id, req.relationship_type)
    return {"ok": True}


@router.get("/{user_id}/{companion_id}")
async def get_relationship(user_id: str, companion_id: str):
    """Return the current relationship stats for a user+companion pair."""
    stats = await relationship.get_stats(user_id, companion_id)
    return stats
