import os
from deepgram import DeepgramClient, PrerecordedOptions, FileSource
from deepgram.errors import DeepgramError

_client: DeepgramClient | None = None


def get_client() -> DeepgramClient:
    global _client
    if _client is None:
        api_key = os.environ.get("DEEPGRAM_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPGRAM_API_KEY environment variable is not set")
        _client = DeepgramClient(api_key)
    return _client


class DeepgramTranscriptError(Exception):
    pass


async def transcribe(
    audio_bytes: bytes,
    mimetype: str = "audio/webm",
    model: str = "nova-2",
    language: str = "en",
    smart_format: bool = True,
    diarize: bool = False,
) -> dict:
    """
    Transcribe audio bytes using Deepgram.

    Returns a dict with:
        transcript  — full text string
        confidence  — float 0-1
        words       — list of {word, start, end, confidence, punctuated_word}
        duration    — audio duration in seconds
    """
    client = get_client()

    payload: FileSource = {
        "buffer": audio_bytes,
        "mimetype": mimetype,
    }

    options = PrerecordedOptions(
        model=model,
        language=language,
        smart_format=smart_format,
        diarize=diarize,
        punctuate=True,
    )

    try:
        response = await client.listen.asyncprerecorded.v("1").transcribe_file(
            payload, options
        )
    except DeepgramError as e:
        raise DeepgramTranscriptError(str(e))
    except Exception as e:
        raise DeepgramTranscriptError(f"Unexpected transcription error: {e}")

    try:
        channel = response.results.channels[0]
        alternative = channel.alternatives[0]
        transcript = alternative.transcript
        confidence = alternative.confidence

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

        duration = getattr(response.metadata, "duration", None)
    except (AttributeError, IndexError) as e:
        raise DeepgramTranscriptError(f"Failed to parse Deepgram response: {e}")

    return {
        "transcript": transcript,
        "confidence": confidence,
        "words": words,
        "duration": duration,
    }
