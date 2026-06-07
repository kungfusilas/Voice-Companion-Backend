import os
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter()

_IMAGINE_URL = "https://api.vyro.ai/v2/image/generations"

_COMPANION_PROMPTS: dict[str, str] = {
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


@router.post("")
async def generate_selfie(request: SelfieRequest):
    """
    Generate an AI selfie for a companion.
    Returns raw image bytes as image/jpeg.
    POST /api/selfie
    """
    prompt = _COMPANION_PROMPTS.get(request.companion_id)
    if not prompt:
        raise HTTPException(status_code=404, detail=f"No selfie prompt for companion '{request.companion_id}'")

    api_key = os.environ.get("IMAGINE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="IMAGINE_API_KEY is not configured")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                _IMAGINE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={
                    "prompt": (None, prompt),
                    "style": (None, "realistic"),
                    "aspect_ratio": (None, "1:1"),
                },
            )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Imagine Art returned {resp.status_code}: {resp.text[:200]}",
            )

        return Response(
            content=resp.content,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Image generation timed out — try again")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
