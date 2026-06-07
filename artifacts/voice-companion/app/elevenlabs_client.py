import os
import asyncio
from typing import AsyncGenerator
from elevenlabs.client import ElevenLabs, AsyncElevenLabs
from elevenlabs.core.api_error import ApiError

# Default to "Rachel" — a built-in ElevenLabs voice
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
DEFAULT_MODEL_ID = "eleven_turbo_v2_5"

_sync_client: ElevenLabs | None = None
_async_client: AsyncElevenLabs | None = None


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
    """Extract a clean, human-readable message from an ElevenLabs ApiError."""
    try:
        body = e.body
        if isinstance(body, dict):
            detail = body.get("detail", {})
            if isinstance(detail, dict):
                return detail.get("message", str(e.body))
            if isinstance(detail, str):
                return detail
        return str(body)
    except Exception:
        return str(e)


class ElevenLabsError(Exception):
    """Raised when ElevenLabs returns an API error, with a clean message."""
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


async def synthesize(
    text: str,
    voice_id: str = DEFAULT_VOICE_ID,
    model_id: str = DEFAULT_MODEL_ID,
) -> bytes:
    """Convert text to speech and return the full audio as bytes (mp3)."""
    def _run() -> bytes:
        client = get_sync_client()
        try:
            chunks = client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id=model_id,
                output_format="mp3_44100_128",
            )
            return b"".join(chunks)
        except ApiError as e:
            raise ElevenLabsError(_friendly_error(e), e.status_code)

    return await asyncio.to_thread(_run)


async def synthesize_stream(
    text: str,
    voice_id: str = DEFAULT_VOICE_ID,
    model_id: str = DEFAULT_MODEL_ID,
) -> AsyncGenerator[bytes, None]:
    """Stream audio chunks as they arrive from ElevenLabs."""
    client = get_async_client()
    try:
        async for chunk in await client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=model_id,
            output_format="mp3_44100_128",
        ):
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
            return [
                {
                    "voice_id": v.voice_id,
                    "name": v.name,
                    "category": v.category,
                    "description": getattr(v, "description", None),
                    "labels": v.labels or {},
                    "preview_url": v.preview_url,
                    "requires_paid_plan": v.category in ("premade", "professional"),
                }
                for v in response.voices
            ]
        except ApiError as e:
            raise ElevenLabsError(_friendly_error(e), e.status_code)

    return await asyncio.to_thread(_run)
