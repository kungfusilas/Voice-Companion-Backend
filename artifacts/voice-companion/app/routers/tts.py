import re
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from app import store
from app import elevenlabs_client
from app.elevenlabs_client import DEFAULT_MODEL_ID, ElevenLabsError, COMPANION_VOICE_SETTINGS
from app.auth_middleware import verify_token_or_guest
from app.usage import check_voice_quota, get_user_tier
from app.routers.tier_check import is_premium_or_higher

router = APIRouter()

# Matches emoji and non-speakable Unicode symbols.
# Covers: supplementary-plane characters (U+10000+, where most emoji live),
# BMP misc-symbol blocks (☀ ⭐ ♠ etc.), variation selectors, and zero-width joiners.
_NON_SPEAKABLE_RE = re.compile(
    "["
    "\U00010000-\U0010FFFF"   # Supplementary planes — emoji, pictographs, etc.
    "\u2600-\u27BF"            # Misc symbols (☀☁⚡), dingbats (✂✈)
    "\u2B00-\u2BFF"            # Misc symbols and arrows (⭐⬛⬜)
    "\u2300-\u23FF"            # Misc technical (⏰⌚)
    "\u25A0-\u25FF"            # Geometric shapes (▪▫◆)
    "\uFE00-\uFE0F"            # Variation selectors (emoji presentation hints)
    "\u200B-\u200D"            # Zero-width space, non-joiner, joiner
    "\uFEFF"                   # BOM / zero-width no-break space
    "]+",
    re.UNICODE,
)


def _strip_non_speakable(text: str) -> str:
    """Remove emoji and non-speakable Unicode so ElevenLabs receives clean text.

    Keeps all Latin, Cyrillic, CJK, Arabic, and other script characters that
    TTS models can handle. Replaces removed runs with a single space so
    sentence rhythm is preserved, then collapses duplicate whitespace.
    """
    cleaned = _NON_SPEAKABLE_RE.sub(" ", text)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


def _elevenlabs_http_error(e: ElevenLabsError) -> HTTPException:
    status = e.status_code if e.status_code in (400, 401, 402, 404, 422) else 502
    return HTTPException(status_code=status, detail=str(e))


class PersonaSpeakRequest(BaseModel):
    text: str
    persona_id: str
    model_id: str = DEFAULT_MODEL_ID


@router.get("/voices")
async def get_voices():
    """List all ElevenLabs voices on your account."""
    try:
        voices = await elevenlabs_client.list_voices()
        return {"voices": voices, "total": len(voices)}
    except ElevenLabsError as e:
        raise _elevenlabs_http_error(e)


@router.post("/speak/stream")
async def persona_speak_stream(
    request: PersonaSpeakRequest,
    req: Request,
    user_id: str = Depends(verify_token_or_guest),
):
    """
    Stream speech using the voice assigned to a persona.
    Returns chunked audio/mpeg — playback can begin as soon as the first chunks arrive.
    Same auth/quota rules as /speak.
    """
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    clean_text = _strip_non_speakable(request.text)
    if not clean_text:
        raise HTTPException(status_code=422, detail="text must not be empty")

    is_guest = user_id.startswith("guest_")
    if is_guest:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "plan_required",
                "required": "premium",
                "message": "Two-Way Voice requires a Premium plan. Sign in and upgrade in Settings → Pricing.",
            },
        )
    tier, _ = await get_user_tier(user_id)
    if not is_premium_or_higher(tier):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "plan_required",
                "required": "premium",
                "message": "Two-Way Voice requires a Premium plan or higher. Upgrade in Settings → Pricing.",
            },
        )
    session_id = req.headers.get("X-Session-Id") or None
    estimated_secs = max(1, len(clean_text) // 13)
    await check_voice_quota(user_id, tier, estimated_secs, session_id)

    voice_settings = COMPANION_VOICE_SETTINGS.get(request.persona_id)

    async def audio_stream():
        try:
            async for chunk in elevenlabs_client.synthesize_stream(
                text=clean_text,
                voice_id=persona.voice_id,
                model_id=request.model_id,
                voice_settings=voice_settings,
            ):
                yield chunk
        except ElevenLabsError as e:
            raise RuntimeError(str(e))

    return StreamingResponse(
        audio_stream(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Content-Disposition": 'inline; filename="speech.mp3"',
        },
    )


@router.post("/speak")
async def persona_speak(
    request: PersonaSpeakRequest,
    req: Request,
    user_id: str = Depends(verify_token_or_guest),
):
    """
    Speak text using the voice assigned to a persona, with per-companion
    voice tuning. Returns full audio as audio/mpeg.

    Requires authentication for paid users. Voice quota is deducted based on
    estimated duration (~13 characters per second).
    """
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    clean_text = _strip_non_speakable(request.text)
    if not clean_text:
        raise HTTPException(status_code=422, detail="text must not be empty")

    is_guest = user_id.startswith("guest_")
    if is_guest:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "plan_required",
                "required": "premium",
                "message": "Two-Way Voice requires a Premium plan. Sign in and upgrade in Settings → Pricing.",
            },
        )
    tier, _ = await get_user_tier(user_id)
    if not is_premium_or_higher(tier):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "plan_required",
                "required": "premium",
                "message": "Two-Way Voice requires a Premium plan or higher. Upgrade in Settings → Pricing.",
            },
        )
    session_id = req.headers.get("X-Session-Id") or None
    estimated_secs = max(1, len(clean_text) // 13)
    await check_voice_quota(user_id, tier, estimated_secs, session_id)

    voice_settings = COMPANION_VOICE_SETTINGS.get(request.persona_id)

    try:
        audio = await elevenlabs_client.synthesize(
            text=clean_text,
            voice_id=persona.voice_id,
            model_id=request.model_id,
            voice_settings=voice_settings,
        )
    except ElevenLabsError as e:
        raise _elevenlabs_http_error(e)

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="speech.mp3"'},
    )
