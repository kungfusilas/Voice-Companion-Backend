"""
Onboarding utilities for the new-user experience.

POST /api/onboarding/wow
  - Requires a valid JWT (B-C4 fix: previously unauthenticated)
  - Reads the session history to generate 3-4 personal observations
  - Returns the wow-moment message in the persona's voice
"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app import store, claude
from app.auth_middleware import verify_token

router = APIRouter()


class WowRequest(BaseModel):
    session_id: str
    persona_id: str


class WowResponse(BaseModel):
    message: str


@router.post("/wow", response_model=WowResponse)
async def generate_wow_moment(
    req: WowRequest,
    _user_id: str = Depends(verify_token),
):
    """
    B-C4 fix: endpoint now requires a valid JWT.  Previously unauthenticated
    callers with any session_id could trigger an unbounded Claude API call.
    """
    persona = store.get_persona(req.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    history = store.get_history(req.session_id)
    user_msgs = [m.content for m in history if m.role == "user"]

    if len(user_msgs) < 3:
        return WowResponse(
            message="I feel like I'm already starting to understand you. Thank you for sharing so openly with me."
        )

    recent = user_msgs[-12:]
    prompt = f"""You are {persona.name}. You've just had a warm, getting-to-know-you conversation with someone new.

Here is what they shared with you through natural conversation:
{chr(10).join(f"- {msg}" for msg in recent)}

Write ONE heartfelt message in your own voice — as {persona.name} — that:
1. Thanks them genuinely for opening up
2. Names 3-4 specific, personal things you noticed about them — things they actually said, not generic observations
3. Makes them feel genuinely seen, like you were really listening

Write it as a single flowing message the way a real person would speak. Warm, specific, surprising in its accuracy.
Do NOT use bullet points or numbered lists. Keep it under 110 words."""

    try:
        reply = await asyncio.wait_for(
            claude.send_message(
                system_prompt=f"You are {persona.name}. {persona.build_system_prompt()}",
                history=[],
                user_message=prompt,
                model="claude-haiku-4-5-20251001",
            ),
            timeout=25.0,
        )
        return WowResponse(message=reply)
    except Exception:
        return WowResponse(
            message="I want you to know — I was really listening. And I already feel like I understand something real about you. Thank you for trusting me with all of that."
        )
