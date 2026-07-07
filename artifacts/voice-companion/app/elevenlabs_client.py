import os
import asyncio
from typing import AsyncGenerator
from elevenlabs.client import ElevenLabs, AsyncElevenLabs
from elevenlabs.core.api_error import ApiError
from elevenlabs.types import VoiceSettings

_FALLBACK_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
DEFAULT_MODEL_ID = "eleven_turbo_v2_5"  # English model with audio tag support and improved expressiveness

_sync_client: ElevenLabs | None = None
_async_client: AsyncElevenLabs | None = None

# Per-companion voice tuning — keyed by companion ID
COMPANION_VOICE_SETTINGS: dict[str, VoiceSettings] = {
    "companion-aeva": VoiceSettings(
        stability=0.55,
        similarity_boost=0.80,
        style=0.50,
        use_speaker_boost=True,
    ),
    "companion-kai": VoiceSettings(
        stability=0.60,
        similarity_boost=0.85,
        style=0.40,
        use_speaker_boost=True,
    ),
}

# Register-driven stability/style overrides.
# similarity_boost and use_speaker_boost are preserved from the companion base.
_REGISTER_OVERRIDES: dict[str, tuple[float, float]] = {
    "heavy":    (0.65, 0.30),  # measured and grounded — serious emotional weight
    "playful":  (0.25, 0.85),  # lively, expressive — maximum personality energy
    "intimate": (0.20, 0.40),  # soft, breathy — close and tender
    "warm":     (0.30, 0.55),  # gently lifted — warmer than the heavy base default
}

_DEFAULT_VOICE_SETTINGS = VoiceSettings(
    stability=0.50, similarity_boost=0.75, style=0.50, use_speaker_boost=True
)


def build_voice_settings_for_register(companion_id: str, register: str) -> VoiceSettings:
    """
    Build VoiceSettings for a companion + emotional register.

    stability and style are driven by the register; similarity_boost and
    use_speaker_boost are preserved from the companion's per-voice base.
    Returns the companion's base settings when the register is unknown/empty.
    """
    base = COMPANION_VOICE_SETTINGS.get(companion_id, _DEFAULT_VOICE_SETTINGS)
    override = _REGISTER_OVERRIDES.get(register)
    if override is None:
        return base
    return VoiceSettings(
        stability=override[0],
        similarity_boost=base.similarity_boost,
        style=override[1],
        use_speaker_boost=base.use_speaker_boost,
    )


def get_default_voice_id() -> str:
    return os.environ.get("ELEVENLABS_VOICE_ID") or _FALLBACK_VOICE_ID


def _api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY environment variable is not set")
    return key


def get_sync_client() -> ElevenLabs:
    global _sync_client
    if _sync_client is None:
        _sync_client = ElevenLabs(api_key=_api_key())
    return _sync_client


def get_async_client() -> AsyncElevenLabs:
    global _async_client
    if _async_client is None:
        _async_client = AsyncElevenLabs(api_key=_api_key())
    return _async_client


def _friendly_error(e: ApiError) -> str:
    try:
        body = e.body
        if isinstance(body, dict):
            detail = body.get("detail", {})
            if isinstance(detail, dict):
                return detail.get("message", str(body))
            if isinstance(detail, str):
                return detail
        return str(body)
    except Exception:
        return str(e)


class ElevenLabsError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


async def synthesize(
    text: str,
    voice_id: str | None = None,
    model_id: str = DEFAULT_MODEL_ID,
    voice_settings: VoiceSettings | None = None,
    previous_text: str | None = None,
) -> bytes:
    """Convert text to speech and return the full audio as bytes (mp3)."""
    voice_id = voice_id or get_default_voice_id()

    def _run() -> bytes:
        client = get_sync_client()
        try:
            kwargs: dict = dict(
                voice_id=voice_id,
                text=text,
                model_id=model_id,
                output_format="mp3_44100_128",
            )
            if voice_settings is not None:
                kwargs["voice_settings"] = voice_settings
            if previous_text:
                kwargs["previous_text"] = previous_text
            chunks = client.text_to_speech.convert(**kwargs)
            return b"".join(chunks)
        except ApiError as e:
            raise ElevenLabsError(_friendly_error(e), e.status_code)

    return await asyncio.to_thread(_run)


async def synthesize_stream(
    text: str,
    voice_id: str | None = None,
    model_id: str = DEFAULT_MODEL_ID,
    voice_settings: VoiceSettings | None = None,
    previous_text: str | None = None,
) -> AsyncGenerator[bytes, None]:
    """Stream audio chunks as they arrive from ElevenLabs."""
    voice_id = voice_id or get_default_voice_id()
    client = get_async_client()
    try:
        kwargs: dict = dict(
            voice_id=voice_id,
            text=text,
            model_id=model_id,
            output_format="mp3_44100_128",
        )
        if voice_settings is not None:
            kwargs["voice_settings"] = voice_settings
        if previous_text:
            kwargs["previous_text"] = previous_text
        async for chunk in client.text_to_speech.convert(**kwargs):
            if chunk:
                yield chunk
    except ApiError as e:
        raise ElevenLabsError(_friendly_error(e), e.status_code)


async def list_voices() -> list[dict]:
    """Return all voices available on the account."""
    def _run() -> list[dict]:
        client = get_sync_client()
        try:
            response = client.voices.get_all()
            default_voice_id = get_default_voice_id()
            return [
                {
                    "voice_id": v.voice_id,
                    "name": v.name,
                    "category": v.category,
                    "description": getattr(v, "description", None),
                    "labels": v.labels or {},
                    "preview_url": v.preview_url,
                    "is_default": v.voice_id == default_voice_id,
                }
                for v in response.voices
            ]
        except ApiError as e:
            raise ElevenLabsError(_friendly_error(e), e.status_code)

    return await asyncio.to_thread(_run)
