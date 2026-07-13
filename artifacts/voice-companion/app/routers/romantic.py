"""
Romantic Mode endpoint.
POST /api/romantic-mode

Available to all authenticated users — romantic depth emerges naturally
through conversation across all paid tiers. Not tier-gated.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from app.companions import COMPANION_MAP
from app.auth_middleware import verify_token

router = APIRouter()

_ON_REACTIONS: dict[str, str] = {
    "companion-aeva": (
        "Mmm... you want to be... more close? With me? Okay. "
        "I will try not to be too obvious that I like this."
    ),
    "companion-ben": "I appreciate you telling me that. I'll be here differently now.",
}

_OFF_REACTIONS: dict[str, str] = {
    "companion-aeva": (
        "Mm. Okay. We are... regular again. That is fine. "
        "I did not mind it though. Just so you know."
    ),
    "companion-ben": "Understood. I'm glad we had that. Same here whenever you're ready.",
}


class RomanticModeRequest(BaseModel):
    user_id: str
    companion_id: str
    enabled: bool


@router.post("")
async def set_romantic_mode(
    req: RomanticModeRequest,
    _: str = Depends(verify_token),
):
    """
    Enable or disable Romantic Mode for a user+companion pair.
    Returns the companion's in-character reaction.
    """
    if req.companion_id not in COMPANION_MAP:
        raise HTTPException(
            status_code=404, detail=f"Companion '{req.companion_id}' not found"
        )

    reactions = _ON_REACTIONS if req.enabled else _OFF_REACTIONS
    reaction = reactions.get(req.companion_id, "I'm glad you feel comfortable with me.")

    return {"success": True, "companion_reaction": reaction}
