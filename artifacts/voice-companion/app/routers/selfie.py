import os
import base64
import httpx
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from app.auth_middleware import verify_token
from app.routers.tier_check import require_premium
from app.usage import check_message_quota, get_user_tier

router = APIRouter()

_VENICE_IMAGE_URL = "https://api.venice.ai/api/v1/image/generate"
_VENICE_IMAGE_MODEL = "flux-2-max"

# Prompts are written from the actual companion avatar images — descriptions must
# match what the user sees on the companion-select screen exactly.
_COMPANION_BASE_PROMPTS: dict[str, str] = {
    # Aeva: East Asian woman, long sleek straight black hair with middle part, NO bangs,
    # light brown eyes, defined arched brows, cat-eye liner, small stud earrings, polished glamorous editorial style
    "companion-aeva": (
        "photorealistic selfie portrait of an East Asian woman in her mid-twenties, "
        "long sleek straight jet-black hair with a clean center middle part, no bangs, "
        "light brown almond-shaped eyes, defined arched dark brows, subtle cat-eye liner, "
        "small diamond stud earrings, porcelain light skin, polished editorial makeup, "
        "glamorous confident composed expression, sophisticated high-fashion style, "
        "black turtleneck, soft even studio-quality lighting, "
        "looking directly at camera, sharp focus, ultra-detailed, editorial selfie"
    ),
    # Kai: white man, short brown hair, chiseled jaw, brown eyes, confident smile
    "companion-kai": (
        "photorealistic selfie portrait of a white man in his early thirties, "
        "short neatly styled brown hair with slight texture, brown eyes, "
        "strong defined chiseled jawline, clean-shaven, light complexion with slight tan, "
        "confident charming subtle smile, athletic build, dark black v-neck t-shirt, "
        "natural studio lighting, looking directly at camera, "
        "sharp focus, ultra-detailed, natural selfie"
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
    Accepts an optional `scene` string to blend context into the image prompt.
    Returns raw image bytes as image/jpeg. Costs 2 message credits.
    POST /api/selfie
    """
    await require_premium(auth_user_id)

    # Selfie generation costs 2 message credits
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
                "decline_message": "I'd love to, but I've hit my limit for this month — catch me next time? 📸",
            },
        ) from quota_exc

    base_prompt = _COMPANION_BASE_PROMPTS.get(request.companion_id)
    if not base_prompt:
        raise HTTPException(
            status_code=404,
            detail=f"No selfie prompt for companion '{request.companion_id}'",
        )

    # Blend optional scene context into the base identity prompt
    scene = (request.scene or "").strip()
    prompt = f"{base_prompt}, {scene}" if scene else base_prompt

    api_key = os.environ.get("VENICE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="Image generation not configured")

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                _VENICE_IMAGE_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model":          _VENICE_IMAGE_MODEL,
                    "prompt":         prompt,
                    "width":          1024,
                    "height":         1024,
                    "steps":          20,
                    "safe_mode":      False,
                    "hide_watermark": True,
                    "return_binary":  False,
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
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Image generation timed out — try again")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
