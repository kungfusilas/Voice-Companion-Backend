"""
Romantic Mode endpoint.
POST /api/romantic-mode
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.companions import COMPANION_MAP

router = APIRouter()

# Hardcoded in-character reactions (tone-perfect, zero latency)
_ON_REACTIONS: dict[str, str] = {
    "companion-aria": "Oh... are we doing this? Okay. I like this side of you.",
    "companion-aeva": (
        "Mmm... you want to be... more close? With me? Okay. "
        "I will try not to be too obvious that I like this."
    ),
    "companion-ember": "Finally. I was starting to think you'd never ask.",
    "companion-kai": "I appreciate you telling me that. I'll be here differently now.",
}

_OFF_REACTIONS: dict[str, str] = {
    "companion-aria": "Of course. Whenever you're ready for more, I'll be here, hehe.",
    "companion-aeva": (
        "Mm. Okay. We are... regular again. That is fine. "
        "I did not mind it though. Just so you know."
    ),
    "companion-ember": "Fair enough. I'm still here — just with a little more distance. For now.",
    "companion-kai": "Understood. I'm glad we had that. Same here whenever you're ready.",
}


class RomanticModeRequest(BaseModel):
    user_id: str
    companion_id: str
    enabled: bool


@router.post("")
async def set_romantic_mode(req: RomanticModeRequest):
    """
    Enable or disable Romantic Mode for a user+companion pair.
    Returns the companion's in-character reaction.
    """
    if req.companion_id not in COMPANION_MAP:
        raise HTTPException(status_code=404, detail=f"Companion '{req.companion_id}' not found")

    # State is owned by the client (localStorage) and sent per-request.
    # DB persistence is deferred until PostgREST schema cache refreshes.
    reactions = _ON_REACTIONS if req.enabled else _OFF_REACTIONS
    reaction = reactions.get(req.companion_id, "I'm glad you feel comfortable with me.")

    return {"success": True, "companion_reaction": reaction}
