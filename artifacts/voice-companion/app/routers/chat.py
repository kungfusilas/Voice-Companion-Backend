import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.models import ChatMessage, ChatRequest, ChatResponse
from app import store, claude, venice_client

router = APIRouter()


def _use_venice(persona_nsfw: bool, request_nsfw: bool) -> bool:
    """Venice is used when either the persona or the per-request flag is True."""
    return persona_nsfw or request_nsfw


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")

    history = store.get_or_create_session(request.session_id, request.persona_id)
    system_prompt = persona.build_system_prompt()
    use_venice = _use_venice(persona.nsfw_mode, request.nsfw_mode)

    if use_venice:
        reply = await venice_client.send_message(
            system_prompt=system_prompt,
            history=history,
            user_message=request.message,
        )
    else:
        reply = await claude.send_message(
            system_prompt=system_prompt,
            history=history,
            user_message=request.message,
        )

    store.append_message(request.session_id, ChatMessage(role="user", content=request.message))
    store.append_message(request.session_id, ChatMessage(role="assistant", content=reply))

    return ChatResponse(
        session_id=request.session_id,
        persona_id=request.persona_id,
        reply=reply,
        message_count=len(store.get_history(request.session_id)),
        model_backend="venice" if use_venice else "claude",
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """
    Stream the companion's reply as Server-Sent Events.

    Each event `data` field contains JSON:
        {"type": "token",  "text": "..."}
        {"type": "done",   "full_text": "...", "message_count": N, "model_backend": "claude"|"venice"}
        {"type": "error",  "message": "..."}
    """
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")

    history = store.get_or_create_session(request.session_id, request.persona_id)
    system_prompt = persona.build_system_prompt()
    use_venice = _use_venice(persona.nsfw_mode, request.nsfw_mode)

    store.append_message(request.session_id, ChatMessage(role="user", content=request.message))

    stream_fn = venice_client.stream_message if use_venice else claude.stream_message

    async def event_generator():
        async for chunk in stream_fn(
            system_prompt=system_prompt,
            history=history,
            user_message=request.message,
        ):
            try:
                raw = chunk.removeprefix("data: ").strip()
                payload = json.loads(raw)
                if payload.get("type") == "done":
                    full_text = payload.get("full_text", "")
                    store.append_message(
                        request.session_id,
                        ChatMessage(role="assistant", content=full_text),
                    )
                    payload["message_count"] = len(store.get_history(request.session_id))
                    payload["model_backend"] = "venice" if use_venice else "claude"
                    yield f"data: {json.dumps(payload)}\n\n"
                    return
            except Exception:
                pass
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
