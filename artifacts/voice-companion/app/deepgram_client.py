import os
from deepgram import AsyncDeepgramClient
from deepgram.types import ListenV1Response

_client: AsyncDeepgramClient | None = None


def get_client() -> AsyncDeepgramClient:
    global _client
    if _client is None:
        api_key = os.environ.get("DEEPGRAM_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPGRAM_API_KEY environment variable is not set")
        _client = AsyncDeepgramClient(api_key=api_key)
    return _client


class DeepgramTranscriptError(Exception):
    pass


async def transcribe(
    audio_bytes: bytes,
    model: str = "nova-2",
    language: str = "en",
    smart_format: bool = True,
    diarize: bool = False,
) -> dict:
    """
    Transcribe audio bytes using Deepgram nova-2.

    Returns:
        transcript  — full text string
        confidence  — float 0-1
        words       — list of {word, punctuated_word, start, end, confidence}
        duration    — audio duration in seconds
    """
    client = get_client()

    try:
        response: ListenV1Response = await client.listen.v1.media.transcribe_file(
            request=audio_bytes,
            model=model,
            language=language,
            smart_format=smart_format,
            punctuate=True,
            diarize=diarize,
        )
    except Exception as e:
        raise DeepgramTranscriptError(f"Deepgram transcription failed: {e}")

    try:
        channel = response.results.channels[0]
        alternative = channel.alternatives[0]

        words = [
            {
                "word": w.word,
                "punctuated_word": getattr(w, "punctuated_word", w.word),
                "start": w.start,
                "end": w.end,
                "confidence": w.confidence,
            }
            for w in (alternative.words or [])
        ]

        return {
            "transcript": alternative.transcript,
            "confidence": alternative.confidence,
            "words": words,
            "duration": getattr(response.metadata, "duration", None),
        }
    except (AttributeError, IndexError) as e:
        raise DeepgramTranscriptError(f"Failed to parse Deepgram response: {e}")
