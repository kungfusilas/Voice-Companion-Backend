"""
Companion selfies - served instantly from a HeyGen-generated warm pool.

The original implementation asked Venice's /image/generate for a photo from a
prose description of the companion. That API takes no reference image, so it
could not reproduce a specific face - it invented a new person on every call.

Aeva and Ben are HeyGen avatars and HeyGen holds a trained LoRA of each, so it
is the only system that can render their real faces in new settings. Look
generation is async, so we generate ahead into a pool (selfie_pool.py) and serve
from it here - instant, and always the real face.

Gating unchanged: Premium+, 2 message credits, and the companion-initiated offer
still runs off the casual-mood + cooldown logic in routers/chat.py.
"""
from __future__ import annotations

import logging
import random

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app import selfie_pool
from app.auth_middleware import verify_token
from app.routers.tier_check import require_premium
from app.usage import check_message_quota, get_user_tier

logger = logging.getLogger(__name__)
router = APIRouter()

_recent: dict[str, list[str]] = {}
_RECENT_KEEP = 5

_DECLINE = "I'd love to send one, but I can't right now - ask me again in a bit?"


class SelfieRequest(BaseModel):
    companion_id: str
    user_id: str
    scene: str | None = None


def _pick(entries: list[dict], scene: str, user_id: str) -> dict | None:
    """Choose the pool entry whose tags best fit the moment, avoiding repeats."""
    if not entries:
        return None

    seen = _recent.get(user_id, [])
    fresh = [e for e in entries if e.get("storage_path") not in seen] or entries

    words = {w.strip(".,!?'\"") for w in scene.lower().split() if len(w) > 2}
    if words:
        scored = [(len(words & {t.lower() for t in (e.get("tags") or [])}), e) for e in fresh]
        best = max(s for s, _ in scored)
        if best > 0:
            fresh = [e for s, e in scored if s == best]

    return random.choice(fresh)


@router.post("")
async def generate_selfie(
    request: SelfieRequest,
    auth_user_id: str = Depends(verify_token),
):
    """Serve a companion selfie from the warm pool. Premium+. Costs 2 message credits."""
    await require_premium(auth_user_id)

    tier, _ = await get_user_tier(auth_user_id)
    try:
        await check_message_quota(auth_user_id, tier, None)
        await check_message_quota(auth_user_id, tier, None)
    except HTTPException as quota_exc:
        base_detail = quota_exc.detail if isinstance(quota_exc.detail, dict) else {}
        raise HTTPException(
            status_code=quota_exc.status_code,
            detail={
                **base_detail,
                "code": "selfie_quota",
                "decline_message": "I'd love to, but I've hit my limit for this month - catch me next time?",
            },
        ) from quota_exc

    entries = await selfie_pool.ready_for(request.companion_id)
    if not entries:
        logger.error(
            "selfie: pool is empty for %r - is HEYGEN_GROUP_* set and has top_up/sync run?",
            request.companion_id,
        )
        raise HTTPException(
            status_code=503,
            detail={"code": "selfie_unavailable", "decline_message": _DECLINE},
        )

    chosen = _pick(entries, (request.scene or "").strip(), auth_user_id)
    if not chosen:
        raise HTTPException(
            status_code=503,
            detail={"code": "selfie_unavailable", "decline_message": _DECLINE},
        )

    path = chosen["storage_path"]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(selfie_pool.public_url(path))
        if resp.status_code != 200:
            raise RuntimeError(f"storage fetch {resp.status_code}")
        img = resp.content
    except Exception as exc:
        logger.error("selfie: fetch failed for %r: %r", path, exc)
        raise HTTPException(
            status_code=503,
            detail={"code": "selfie_unavailable", "decline_message": _DECLINE},
        )

    hist = _recent.setdefault(auth_user_id, [])
    hist.append(path)
    del hist[:-_RECENT_KEEP]

    logger.info("selfie: served %s to user=%s (scene=%r)", path, auth_user_id, request.scene)

    return Response(
        content=img,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )
