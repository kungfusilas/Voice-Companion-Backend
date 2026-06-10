"""
Usage metering & session management endpoints.

  GET  /api/usage/status      — current month's quota usage (auth required)
  POST /api/session/register  — store a client session ID at login (auth required)
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth_middleware import verify_token
from app.usage import get_usage_status, get_user_tier, register_session

router = APIRouter()


@router.get("/usage/status")
async def usage_status(user_id: str = Depends(verify_token)):
    tier, _ = await get_user_tier(user_id)
    return await get_usage_status(user_id, tier)


class RegisterSessionRequest(BaseModel):
    session_id: str


@router.post("/session/register")
async def session_register(
    req: RegisterSessionRequest,
    user_id: str = Depends(verify_token),
):
    await register_session(user_id, req.session_id)
    return {"ok": True}
