from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from app import store
from app import elevenlabs_client
from app.elevenlabs_client import DEFAULT_MODEL_ID, ElevenLabsError, COMPANION_VOICE_SETTINGS

router = APIRouter()


def _elevenlabs_http_error(e: ElevenLabsError) -> HTTPException:
    status = e.status_code if e.status_code in (400, 401, 402, 404, 422) else 502
    return HTTPException(status_code=status, detail=str(e))


class TTSRequest(BaseModel):
    text: str
    voice_id: str | None = None
    model_id: str = DEFAULT_MODEL_ID


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


@router.post("", response_class=Response)
async def text_to_speech(request: TTSRequest):
    """Convert text to speech. Returns full audio as audio/mpeg."""
    if not request.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")

    try:
        audio = await elevenlabs_client.synthesize(
            text=request.text,
            voice_id=request.voice_id,
            model_id=request.model_id,
        )
    except ElevenLabsError as e:
        raise _elevenlabs_http_error(e)

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="speech.mp3"'},
    )


@router.post("/stream")
async def text_to_speech_stream(request: TTSRequest):
    """Stream audio chunks from ElevenLabs (lower latency)."""
    if not request.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")

    async def audio_generator():
        try:
            async for chunk in elevenlabs_client.synthesize_stream(
                text=request.text,
                voice_id=request.voice_id,
                model_id=request.model_id,
            ):
                yield chunk
        except ElevenLabsError as e:
            raise RuntimeError(str(e))

    return StreamingResponse(
        audio_generator(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Content-Disposition": 'inline; filename="speech.mp3"',
        },
    )


@router.post("/speak")
async def persona_speak(request: PersonaSpeakRequest):
    """
    Speak text using the voice assigned to a persona, with per-companion
    voice tuning (stability, style, similarity_boost).
    Returns full audio as audio/mpeg.
    """
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    if not request.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")

    voice_settings = COMPANION_VOICE_SETTINGS.get(request.persona_id)

    try:
        audio = await elevenlabs_client.synthesize(
            text=request.text,
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
