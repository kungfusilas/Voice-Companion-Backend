import os
import base64
import httpx
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from app.auth_middleware import verify_token
from app.routers.tier_check import require_premium

router = APIRouter()

_VENICE_IMAGE_URL = "https://api.venice.ai/api/v1/image/generate"

_COMPANION_BASE_PROMPTS: dict[str, str] = {
    "companion-aria": (
        "cute shy Asian girl with long black hair, soft smile, casual cozy outfit, "
        "warm lighting, selfie style photo, photorealistic"
    ),
    "companion-aeva": (
        "confident beautiful woman with wavy auburn hair, bold glamorous style, "
        "dramatic lighting, selfie style photo, photorealistic"
    ),
    "companion-ember": (
        "energetic girl with bright red hair in a ponytail, sporty outfit, "
        "big smile, outdoor selfie, natural lighting, photorealistic"
    ),
    "companion-kai": (
        "calm handsome man with dark hair, gentle expression, casual style, "
        "natural lighting, selfie photo, photorealistic"
    ),
}


class SelfieRequest(BaseModel):
    companion_id: str
    user_id: str
    scene: str | None = None


@router.post("")
async def generate_selfie(
    request: SelfieRequest,
    auth_user_id: str = Depends(verify_token),
):
    """
    Generate an AI selfie for a companion using Venice image generation. Premium+.
    Accepts an optional `scene` string to blend imaginative context into the prompt.
    Returns raw image bytes as image/png.
    POST /api/selfie
    """
    await require_premium(auth_user_id)

    base_prompt = _COMPANION_BASE_PROMPTS.get(request.companion_id)
    if not base_prompt:
        raise HTTPException(
            status_code=404,
            detail=f"No selfie prompt for companion '{request.companion_id}'",
        )

    # Blend scene context into the base prompt when provided
    scene = (request.scene or "").strip()
    prompt = f"{base_prompt}, {scene}" if scene else base_prompt

    api_key = os.environ.get("VENICE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="Image generation not configured")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                _VENICE_IMAGE_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model":          "fluently-xl",
                    "prompt":         prompt,
                    "width":          1024,
                    "height":         1024,
                    "steps":          20,
                    "safe_mode":      False,
                    "hide_watermark": True,
                    "return_binary":  False,
                    "style_preset":   "Photographic",
                },
            )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Image generation failed ({resp.status_code}): {resp.text[:200]}",
            )

        data = resp.json()
        images = data.get("images", [])
        if not images:
            raise HTTPException(status_code=502, detail="No image returned from generation service")

        # Venice returns images as a list of base64 strings or dicts with url/b64_json
        first = images[0]
        if isinstance(first, str):
            img_bytes = base64.b64decode(first)
        elif isinstance(first, dict):
            b64 = first.get("b64_json") or first.get("url", "")
            if b64.startswith("data:"):
                b64 = b64.split(",", 1)[1]
            img_bytes = base64.b64decode(b64)
        else:
            raise HTTPException(status_code=502, detail="Unexpected image format from generation service")

        return Response(
            content=img_bytes,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Image generation timed out — try again")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
