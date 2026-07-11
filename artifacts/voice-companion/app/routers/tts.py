import asyncio
import logging
import re
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from app import store
from app import elevenlabs_client
from app import openai_tts_client
from app.elevenlabs_client import (
    DEFAULT_MODEL_ID,
    ElevenLabsError,
    build_voice_settings_for_register,
)
from app.openai_tts_client import OpenAITTSError
from app.auth_middleware import verify_token_or_guest
from app.usage import check_voice_quota, get_user_tier
from app.routers.tier_check import is_premium_or_higher, is_power_or_higher

router = APIRouter()
logger = logging.getLogger("tts")

# Hard timeouts for TTS providers. A stalled provider call can hang without ever
# raising an exception, which freezes the client. These caps guarantee we fall
# back to text-only (voice_available: false) instead of waiting forever.
_ELEVEN_TIMEOUT = 12.0
_OPENAI_TIMEOUT = 10.0


async def _stream_with_timeout(agen, timeout: float, label: str):
    """Yield chunks from an async audio generator, ending the stream if any
    single chunk stalls longer than `timeout` seconds.

    This is a per-chunk cap (not a total-duration cap) so long-but-healthy audio
    keeps flowing while a genuine hang is bounded. Non-timeout exceptions (e.g.
    ElevenLabsError) propagate to the caller so existing retry/degrade logic runs.
    """
    it = agen.__aiter__()
    try:
        while True:
            try:
                chunk = await asyncio.wait_for(it.__anext__(), timeout=timeout)
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError:
                logger.warning("%s timed out after %ss — ending stream, falling back to text-only", label, timeout)
                return
            yield chunk
    finally:
        aclose = getattr(agen, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                pass

# Sent when speech synthesis fails but the chat text is still available.
# The frontend reads this header to degrade gracefully (show text, no audio)
# instead of treating a TTS failure as a fatal error that breaks the send flow.
VOICE_UNAVAILABLE_HEADERS = {
    "X-Voice-Available": "false",
    "Content-Disposition": 'inline; filename="speech.mp3"',
}

# Matches LLM action descriptors that TTS would read literally.
# Strips asterisk-, bracket-, and paren-wrapped stage directions, e.g.
# *laughs*, [sighs], (chuckles softly).
_ACTION_DESCRIPTOR_RE = re.compile(
    r"\*[^*]*(?:laugh|sigh|chuckle|giggle|smile|pause|gasp|groan|sniffle|cr[yi]|whisper|clears?\s+(?:her\s+|his\s+|their\s+)?throat)[^*]*\*"
    r"|\[[^\]]*(?:laugh|sigh|chuckle|giggle|smile|pause|gasp|groan|sniffle|cr[yi]|whisper|clears?\s+(?:her\s+|his\s+|their\s+)?throat)[^\]]*\]"
    r"|\([^)]*(?:laugh|sigh|chuckle|giggle|smile|pause|gasp|groan|sniffle|cr[yi]|whisper|clears?\s+(?:her\s+|his\s+|their\s+)?throat)[^)]*\)",
    re.IGNORECASE,
)


def sanitize_for_tts(text: str) -> str:
    """Strip LLM action descriptors that TTS would vocalise literally.

    Removes patterns like *laughs*, [sighs softly], (chuckles), etc.
    Intentional ElevenLabs audio tags injected later by _inject_el_tags()
    are unaffected — they are added after this step.
    """
    cleaned = _ACTION_DESCRIPTOR_RE.sub("", text)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


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


# ── Emotional register detection ───────────────────────────────────────────────

_HEAVY_SIGNALS = [
    "that's hard", "that must be", "i'm so sorry", "that hurts", "must be tough",
    "sounds like a lot", "struggling", "grief", "loss", "afraid", "worried",
    "scared", "exhausted", "drained", "can't stop", "breaking", "overwhelmed",
    "rough day", "hard day", "hard time", "been hard", "really hard",
    "miss you", "missed you", "missing you", "i hear you", "i see you",
    "makes sense you'd feel", "that's a lot to carry", "not easy",
]

_PLAYFUL_SIGNALS = [
    "haha", "lol", "lmao", "omg", "wait what", "no way", "seriously?",
    "that's hilarious", "that's amazing", "genius", "finally", "love that",
    "i love that", "oh wow", "oh my", "get out of here", "stop it",
]

_INTIMATE_SIGNALS = [
    "just between", "i've been thinking", "honestly,", "can i tell you",
    "between you and me", "i have to admit", "truth is,", "to be honest,",
]


def _detect_register(text: str) -> str:
    """
    Classify a TTS text snippet into one of four emotional registers for voice delivery.
    Returns: "heavy" | "playful" | "intimate" | "warm" (default).

    Detection is heuristic — lightweight, zero-latency, and deterministic.
    Only the CLEAN spoken text arrives here (tags/markdown already stripped by frontend).
    """
    lower = text.lower()
    char_len = len(text.strip())
    exclamation_count = text.count("!")

    heavy_hits = sum(1 for s in _HEAVY_SIGNALS if s in lower)
    playful_hits = sum(1 for s in _PLAYFUL_SIGNALS if s in lower)
    intimate_hit = (
        char_len < 130
        and any(p in lower for p in _INTIMATE_SIGNALS)
    )

    if heavy_hits >= 2 or (heavy_hits >= 1 and exclamation_count == 0 and char_len > 40):
        return "heavy"
    if playful_hits >= 1 or exclamation_count >= 3:
        return "playful"
    if intimate_hit:
        return "intimate"
    return "warm"


def _inject_el_tags(text: str, register: str) -> str:
    """
    Insert at most one ElevenLabs audio tag at a natural break point.

    Rules:
      heavy   → prepend [sighs] — voice sighs before the empathetic reply
      playful → append [laughs] after the first exclamatory moment
      intimate/warm → no tag; VoiceSettings carry the register instead

    Falls back to plain text for very short inputs or when no natural
    insertion point exists. Tags are silent to the chat UI — they only reach
    ElevenLabs because they're injected after the frontend's display-strip pass.
    """
    if not text or len(text.strip()) < 20:
        return text

    if register == "heavy":
        return f"[sighs] {text}"

    if register == "playful":
        m = re.search(r"([^.!?]*!)", text)
        if m:
            end = m.end()
            return text[:end] + " [laughs]" + text[end:]
        return text

    return text


def _elevenlabs_http_error(e: ElevenLabsError) -> HTTPException:
    status = e.status_code if e.status_code in (400, 401, 402, 404, 422) else 502
    return HTTPException(status_code=status, detail=str(e))


class PersonaSpeakRequest(BaseModel):
    text: str
    persona_id: str
    model_id: str = DEFAULT_MODEL_ID
    previous_text: str | None = None


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

    Emotional register is detected from the clean text and drives both:
      - VoiceSettings (stability/style per register)
      - ElevenLabs audio tags ([sighs], [laughs]) injected before synthesis
    Tags never appear in the chat UI — they're injected here after the frontend's
    display-strip pass.
    """
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    clean_text = _strip_non_speakable(sanitize_for_tts(request.text))
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

    logger.info(f"[TTS] starting for user={user_id}")

    # Premium tier uses OpenAI TTS (tts-1-hd, per-persona voice). Power+ keeps ElevenLabs unchanged.
    if not is_power_or_higher(tier):
        async def openai_audio_stream():
            try:
                async for chunk in _stream_with_timeout(
                    openai_tts_client.synthesize_stream(clean_text, voice=openai_tts_client.voice_for_persona(persona.id)),
                    _OPENAI_TIMEOUT,
                    "OpenAI TTS",
                ):
                    yield chunk
                logger.info(f"[TTS] done for user={user_id}")
            except OpenAITTSError as e:
                # Degrade gracefully — end the stream instead of raising so the
                # frontend gets a clean (possibly empty) 200 and shows text.
                logger.warning("OpenAI TTS stream failed, degrading to text-only: %s", e)
                return

        return StreamingResponse(
            openai_audio_stream(),
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Content-Disposition": 'inline; filename="speech.mp3"',
            },
        )

    register = _detect_register(clean_text)
    tagged_text = _inject_el_tags(clean_text, register)
    voice_settings = build_voice_settings_for_register(request.persona_id, register)

    async def audio_stream():
        try:
            async for chunk in _stream_with_timeout(
                elevenlabs_client.synthesize_stream(
                    text=tagged_text,
                    voice_id=persona.voice_id,
                    model_id=request.model_id,
                    voice_settings=voice_settings,
                    previous_text=request.previous_text or None,
                ),
                _ELEVEN_TIMEOUT,
                "ElevenLabs",
            ):
                yield chunk
            logger.info(f"[TTS] done for user={user_id}")
        except ElevenLabsError as e:
            if tagged_text != clean_text:
                # Tag may have caused the rejection — retry with plain text
                try:
                    async for chunk in _stream_with_timeout(
                        elevenlabs_client.synthesize_stream(
                            text=clean_text,
                            voice_id=persona.voice_id,
                            model_id=request.model_id,
                            voice_settings=voice_settings,
                            previous_text=request.previous_text or None,
                        ),
                        _ELEVEN_TIMEOUT,
                        "ElevenLabs",
                    ):
                        yield chunk
                    logger.info(f"[TTS] done for user={user_id}")
                except ElevenLabsError as e2:
                    logger.warning("ElevenLabs TTS stream failed, degrading to text-only: %s", e2)
                    return
            else:
                logger.warning("ElevenLabs TTS stream failed, degrading to text-only: %s", e)
                return

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
    voice tuning and register-driven emotional delivery.
    Returns full audio as audio/mpeg.

    Requires authentication for paid users. Voice quota is deducted based on
    estimated duration (~13 characters per second).
    """
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    clean_text = _strip_non_speakable(sanitize_for_tts(request.text))
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

    logger.info(f"[TTS] starting for user={user_id}")

    # Premium tier uses OpenAI TTS (tts-1-hd, per-persona voice). Power+ keeps ElevenLabs unchanged.
    if not is_power_or_higher(tier):
        try:
            audio = await asyncio.wait_for(
                openai_tts_client.synthesize(clean_text, voice=openai_tts_client.voice_for_persona(persona.id)),
                timeout=_OPENAI_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("OpenAI TTS timed out after %ss — falling back to text-only", _OPENAI_TIMEOUT)
            return Response(content=b"", media_type="audio/mpeg", headers=VOICE_UNAVAILABLE_HEADERS)
        except OpenAITTSError as e:
            # Voice synthesis failed — degrade gracefully to text-only.
            # Return 200 with an empty body + X-Voice-Available: false so the
            # frontend shows the chat text and never enters a broken send state.
            logger.warning("OpenAI TTS failed, degrading to text-only: %s", e)
            return Response(content=b"", media_type="audio/mpeg", headers=VOICE_UNAVAILABLE_HEADERS)

        logger.info(f"[TTS] done for user={user_id}")
        return Response(
            content=audio,
            media_type="audio/mpeg",
            headers={"Content-Disposition": 'inline; filename="speech.mp3"'},
        )

    register = _detect_register(clean_text)
    tagged_text = _inject_el_tags(clean_text, register)
    voice_settings = build_voice_settings_for_register(request.persona_id, register)

    try:
        audio = await asyncio.wait_for(
            elevenlabs_client.synthesize(
                text=tagged_text,
                voice_id=persona.voice_id,
                model_id=request.model_id,
                voice_settings=voice_settings,
                previous_text=request.previous_text or None,
            ),
            timeout=_ELEVEN_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("ElevenLabs timed out after %ss — falling back to text-only", _ELEVEN_TIMEOUT)
        return Response(content=b"", media_type="audio/mpeg", headers=VOICE_UNAVAILABLE_HEADERS)
    except ElevenLabsError as e:
        if tagged_text != clean_text:
            # Tag may have caused the rejection — retry with plain text
            try:
                audio = await asyncio.wait_for(
                    elevenlabs_client.synthesize(
                        text=clean_text,
                        voice_id=persona.voice_id,
                        model_id=request.model_id,
                        voice_settings=voice_settings,
                        previous_text=request.previous_text or None,
                    ),
                    timeout=_ELEVEN_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("ElevenLabs timed out after %ss — falling back to text-only", _ELEVEN_TIMEOUT)
                return Response(content=b"", media_type="audio/mpeg", headers=VOICE_UNAVAILABLE_HEADERS)
            except ElevenLabsError as e2:
                # Voice synthesis failed — degrade gracefully to text-only.
                logger.warning("ElevenLabs TTS failed, degrading to text-only: %s", e2)
                return Response(content=b"", media_type="audio/mpeg", headers=VOICE_UNAVAILABLE_HEADERS)
        else:
            logger.warning("ElevenLabs TTS failed, degrading to text-only: %s", e)
            return Response(content=b"", media_type="audio/mpeg", headers=VOICE_UNAVAILABLE_HEADERS)

    logger.info(f"[TTS] done for user={user_id}")
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="speech.mp3"'},
    )
