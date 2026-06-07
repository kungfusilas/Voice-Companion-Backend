from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from app import store
from app import elevenlabs_client
from app.elevenlabs_client import DEFAULT_VOICE_ID, DEFAULT_MODEL_ID, ElevenLabsError

router = APIRouter()

_PLAN_HINT = (
    "ElevenLabs free accounts cannot use premade/library voices via the API. "
    "Options: (1) upgrade your ElevenLabs plan, or (2) create a personal voice "
    "at elevenlabs.io/voice-lab and pass its voice_id instead."
)


def _elevenlabs_http_error(e: ElevenLabsError) -> HTTPException:
    """Map an ElevenLabsError to a clean FastAPI HTTPException."""
    # 402 = plan required → surface the hint
    detail = f"{e} — {_PLAN_HINT}" if e.status_code == 402 else str(e)
    status = 402 if e.status_code == 402 else 502
    return HTTPException(status_code=status, detail=detail)


class TTSRequest(BaseModel):
    text: str
    voice_id: str = DEFAULT_VOICE_ID
    model_id: str = DEFAULT_MODEL_ID


class PersonaSpeakRequest(BaseModel):
    text: str
    persona_id: str
    model_id: str = DEFAULT_MODEL_ID


@router.get("/voices")
async def get_voices():
    """
    List all ElevenLabs voices on your account.
    `requires_paid_plan: true` means the voice cannot be used on the free tier.
    """
    try:
        voices = await elevenlabs_client.list_voices()
        return {"voices": voices, "total": len(voices)}
    except ElevenLabsError as e:
        raise _elevenlabs_http_error(e)


@router.post("", response_class=Response)
async def text_to_speech(request: TTSRequest):
    """
    Convert text to speech. Returns the full audio file as **audio/mpeg**.

    For lower latency, use `POST /api/tts/stream` to begin playback as the
    audio is generated.

    **Free-tier note:** premade voices require an ElevenLabs paid plan.
    Create a personal voice at elevenlabs.io/voice-lab and pass its `voice_id`.
    """
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
    """
    Stream audio chunks as they arrive from ElevenLabs (lower latency).
    Use with the Web Audio API or MediaSource Extensions on the frontend.

    **Free-tier note:** premade voices require an ElevenLabs paid plan.
    """
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
            # Can't raise HTTP exceptions mid-stream; raise so uvicorn closes cleanly
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
    Speak text using the voice assigned to a specific persona.
    Falls back to the default voice if the persona has no `voice_id` set.
    Returns full audio as **audio/mpeg**.
    """
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    voice_id = persona.voice_id or DEFAULT_VOICE_ID

    if not request.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")

    try:
        audio = await elevenlabs_client.synthesize(
            text=request.text,
            voice_id=voice_id,
            model_id=request.model_id,
        )
    except ElevenLabsError as e:
        raise _elevenlabs_http_error(e)

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="speech.mp3"'},
    )
