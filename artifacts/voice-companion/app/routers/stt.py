import asyncio
from fastapi import APIRouter, HTTPException, UploadFile, File, Query, Depends, Request
from app import deepgram_client
from app.deepgram_client import DeepgramTranscriptError
from app.auth_middleware import verify_token_or_guest
from app.usage import check_voice_quota, get_user_tier
from app import language as lang_module

router = APIRouter()

_SUPPORTED_TYPES = {
    "audio/webm",
    "audio/webm;codecs=opus",
    "audio/ogg",
    "audio/ogg;codecs=opus",
    "audio/mp4",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
    "audio/m4a",
    "audio/aac",
    "video/webm",
}


@router.post("")
async def speech_to_text(
    req: Request,
    audio: UploadFile = File(..., description="Audio file to transcribe"),
    model: str = Query("nova-2", description="Deepgram model — nova-2 recommended"),
    language: str = Query("", description="BCP-47 language hint (empty = auto-detect)"),
    diarize: bool = Query(False, description="Identify multiple speakers"),
    user_id: str = Depends(verify_token_or_guest),
):
    """
    Transcribe speech from an uploaded audio file.

    Language selection priority:
    1. If `language` query param is explicitly provided, use it.
    2. For authenticated users: look up their preferred_language from profile.
    3. Fall back to Deepgram auto language detection (nova-2 supports it natively).

    Requires authentication for paid users. Voice quota is deducted based on
    estimated audio duration (webm/opus ≈ 4 000 bytes/sec).
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Uploaded audio file is empty")

    if len(audio_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file too large (max 25 MB)")

    is_guest = user_id.startswith("guest_")

    if not is_guest:
        tier, _ = await get_user_tier(user_id)
        session_id = req.headers.get("X-Session-Id") or None
        estimated_secs = max(1, len(audio_bytes) // 4000)
        await check_voice_quota(user_id, tier, estimated_secs, session_id)

    # Always use detect_language=True — never feed the stored preferred_language
    # into Deepgram because a single wrong auto-detection permanently poisons it,
    # causing all subsequent calls for that user to return empty transcripts.
    # The detected language is still saved below (for prompts etc) but is never
    # used as a Deepgram language hint.
    try:
        result = await deepgram_client.transcribe(
            audio_bytes=audio_bytes,
            model=model,
            diarize=diarize,
            detect_language=True,
        )
    except DeepgramTranscriptError as e:
        raise HTTPException(status_code=502, detail=f"Deepgram error: {e}")

    # Keep preferred_language in sync with what Deepgram actually heard
    if not is_guest and result.get("detected_language"):
        detected = result["detected_language"]
        if detected:
            asyncio.create_task(lang_module.set_preferred_language(user_id, detected))

    return result
