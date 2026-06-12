"""
Lightweight client-side diagnostic log sink.

The frontend POSTs structured log entries here from the TTS pipeline so
that audio failures (AudioContext state, decodeAudioData errors, element
play() rejections) are visible server-side with zero user effort.
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth_middleware import verify_token

logger = logging.getLogger(__name__)
router = APIRouter()


class ClientLogRequest(BaseModel):
    event: str
    data: dict[str, Any] = {}


@router.post("/client-log")
async def client_log(
    body: ClientLogRequest,
    user_id: str = Depends(verify_token),
):
    """Receive a client-side diagnostic log entry and write it to the server log."""
    logger.info("[CLIENT] uid=%.8s event=%s data=%s", user_id, body.event, body.data)
    return {"ok": True}
