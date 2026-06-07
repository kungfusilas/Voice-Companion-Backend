from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from app import deepgram_client
from app.deepgram_client import DeepgramTranscriptError

router = APIRouter()

# Audio MIME types we accept and their Deepgram-compatible labels
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
    "video/webm",   # Chrome MediaRecorder sometimes uses this for audio
}


@router.post("")
async def speech_to_text(
    audio: UploadFile = File(..., description="Audio file to transcribe"),
    model: str = Query("nova-2", description="Deepgram model — nova-2 recommended"),
    language: str = Query("en", description="BCP-47 language code, e.g. 'en', 'es', 'fr'"),
    diarize: bool = Query(False, description="Identify multiple speakers"),
):
    """
    Transcribe speech from an uploaded audio file.

    Accepts any common audio format: webm, ogg, mp3, wav, flac, mp4, m4a.
    Returns a full transcript, per-word timings, and confidence scores.

    **Typical frontend flow (browser MediaRecorder):**
    ```js
    const recorder = new MediaRecorder(stream);
    recorder.ondataavailable = async (e) => {
      const form = new FormData();
      form.append('audio', e.data, 'recording.webm');
      const res = await fetch('/api/stt', { method: 'POST', body: form });
      const { transcript } = await res.json();
    };
    ```
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Uploaded audio file is empty")

    if len(audio_bytes) > 25 * 1024 * 1024:  # 25 MB guard
        raise HTTPException(status_code=413, detail="Audio file too large (max 25 MB)")

    try:
        result = await deepgram_client.transcribe(
            audio_bytes=audio_bytes,
            model=model,
            language=language,
            diarize=diarize,
        )
    except DeepgramTranscriptError as e:
        raise HTTPException(status_code=502, detail=f"Deepgram error: {e}")

    return result
