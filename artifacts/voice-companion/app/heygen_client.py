"""
HeyGen Photo Avatar client.

Aeva and Ben are HeyGen avatars. HeyGen holds a *trained LoRA* of each, which
makes it the only system that can render their actual faces in new outfits and
settings. The previous Venice integration only ever received a prose description
of the companion, so it invented a new stranger on every call.

  POST /v2/photo_avatar/look/generate   - generate a new look (async)
  GET  /v2/avatar_group/{id}/avatars    - list the looks in a group

Look generation is ASYNCHRONOUS (tens of seconds), which is why selfies are
served from a warm pool rather than generated inside the request.

Docs: https://docs.heygen.com/docs/photo-avatars-api
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.heygen.com"

ORIENTATIONS = {"square", "horizontal", "vertical"}
POSES = {"half_body", "close_up", "full_body"}
STYLES = {"Realistic", "Pixar", "Cinematic", "Vintage", "Noir", "Cyberpunk", "Unspecified"}

_PROMPT_MAX = 1000


class HeyGenError(Exception):
    pass


def _key() -> str:
    key = os.environ.get("HEYGEN_API_KEY", "").strip()
    if not key:
        raise HeyGenError("HEYGEN_API_KEY is not configured")
    return key


def _headers() -> dict[str, str]:
    return {"x-api-key": _key(), "Content-Type": "application/json"}


def group_for(companion_id: str) -> str | None:
    """Map a companion to its trained HeyGen avatar group.

    Set in Replit Secrets:
      HEYGEN_GROUP_AEVA=ag_xxxxxxxx
      HEYGEN_GROUP_BEN=ag_yyyyyyyy
    """
    env_key = {
        "companion-aeva": "HEYGEN_GROUP_AEVA",
        "companion-ben":  "HEYGEN_GROUP_BEN",
    }.get(companion_id)
    if not env_key:
        return None
    return os.environ.get(env_key, "").strip() or None


async def generate_look(
    group_id: str,
    prompt: str,
    *,
    orientation: str = "vertical",
    pose: str = "close_up",
    style: str = "Realistic",
) -> str:
    """Kick off generation of a new look. Returns HeyGen's generation id.

    Asynchronous - the image is NOT ready when this returns.
    """
    if orientation not in ORIENTATIONS:
        raise HeyGenError(f"invalid orientation {orientation!r}")
    if pose not in POSES:
        raise HeyGenError(f"invalid pose {pose!r}")
    if style not in STYLES:
        raise HeyGenError(f"invalid style {style!r}")

    body = {
        "group_id":    group_id,
        "prompt":      prompt[:_PROMPT_MAX],
        "orientation": orientation,
        "pose":        pose,
        "style":       style,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{_BASE}/v2/photo_avatar/look/generate",
            headers=_headers(),
            json=body,
        )
    if resp.status_code != 200:
        raise HeyGenError(f"look/generate failed ({resp.status_code}): {resp.text[:300]}")

    data = resp.json().get("data") or {}
    gen_id = data.get("generation_id") or data.get("id") or ""
    logger.info("heygen: look generation started group=%s gen=%s", group_id, gen_id)
    return gen_id


async def list_group_looks(group_id: str) -> list[dict]:
    """Return the looks in an avatar group."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{_BASE}/v2/avatar_group/{group_id}/avatars",
            headers=_headers(),
        )
    if resp.status_code != 200:
        raise HeyGenError(f"list looks failed ({resp.status_code}): {resp.text[:300]}")

    payload = resp.json().get("data") or {}
    if isinstance(payload, dict):
        looks = payload.get("avatar_list") or payload.get("looks") or []
    else:
        looks = payload or []
    return [lk for lk in looks if isinstance(lk, dict)]


def look_image_url(look: dict) -> str | None:
    for field in ("image_url", "preview_image_url", "url", "image"):
        val = look.get(field)
        if isinstance(val, str) and val.startswith("http"):
            return val
    return None


def look_is_ready(look: dict) -> bool:
    status = (look.get("status") or "").lower()
    return status in ("", "completed", "success", "ready")
