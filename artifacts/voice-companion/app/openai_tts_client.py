"""
openai_tts_client.py — LegacyBond AI

OpenAI TTS backend used for the Premium tier (Power tier keeps ElevenLabs,
see elevenlabs_client.py). Mirrors the synthesize()/synthesize_stream() shape
of elevenlabs_client.py so callers in routers/tts.py can branch on tier
without changing their calling convention.

Model: tts-1-hd. Voice is per-persona: Aeva → nova, Ben → onyx (deep male).
Default voice is nova.
"""
import os
from typing import AsyncGenerator

from openai import AsyncOpenAI

TTS_MODEL = "tts-1-hd"
TTS_VOICE = "nova"

# Per-persona OpenAI voice mapping (Premium tier)
PERSONA_VOICES = {
    "companion-aeva": "nova",
    "companion-ben": "onyx",
}


def voice_for_persona(persona_id: str) -> str:
    return PERSONA_VOICES.get(persona_id, TTS_VOICE)

_async_client: AsyncOpenAI | None = None


class OpenAITTSError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")
    return key


def get_async_client() -> AsyncOpenAI:
    global _async_client
    if _async_client is None:
        _async_client = AsyncOpenAI(api_key=_api_key())
    return _async_client


async def synthesize(text: str, voice: str = TTS_VOICE) -> bytes:
    """Convert text to speech via OpenAI TTS and return full audio as bytes (mp3)."""
    try:
        client = get_async_client()
        response = await client.audio.speech.create(
            model=TTS_MODEL,
            voice=voice,
            input=text,
        )
        return response.read()
    except Exception as e:
        raise OpenAITTSError(str(e))


async def synthesize_stream(text: str, voice: str = TTS_VOICE) -> AsyncGenerator[bytes, None]:
    """Stream audio chunks as they arrive from OpenAI TTS."""
    try:
        client = get_async_client()
        async with client.audio.speech.with_streaming_response.create(
            model=TTS_MODEL,
            voice=voice,
            input=text,
        ) as response:
            async for chunk in response.iter_bytes():
                if chunk:
                    yield chunk
    except Exception as e:
        raise OpenAITTSError(str(e))
