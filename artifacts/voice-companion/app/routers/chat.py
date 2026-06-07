import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.models import ChatMessage, ChatRequest, ChatResponse
from app import store, claude

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")

    history = store.get_or_create_session(request.session_id, request.persona_id)
    system_prompt = persona.build_system_prompt()

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
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """
    Stream the companion's reply as Server-Sent Events.

    Connect with EventSource or fetch + ReadableStream. Each event has a `data`
    field containing JSON:

        {"type": "token",  "text": "..."}          — partial text chunk
        {"type": "done",   "full_text": "..."}      — stream finished; full reply included
        {"type": "error",  "message": "..."}        — something went wrong

    The user message is appended to history immediately. The assistant turn is
    committed once the full reply is assembled (on the "done" event).
    """
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")

    history = store.get_or_create_session(request.session_id, request.persona_id)
    system_prompt = persona.build_system_prompt()

    store.append_message(request.session_id, ChatMessage(role="user", content=request.message))

    async def event_generator():
        full_text = ""
        async for chunk in claude.stream_message(
            system_prompt=system_prompt,
            history=history,
            user_message=request.message,
        ):
            # Parse the payload to detect "done" and persist the assistant turn
            try:
                raw = chunk.removeprefix("data: ").strip()
                payload = json.loads(raw)
                if payload.get("type") == "done":
                    full_text = payload.get("full_text", "")
                    store.append_message(
                        request.session_id,
                        ChatMessage(role="assistant", content=full_text),
                    )
                    # Enrich the done event with message_count
                    payload["message_count"] = len(store.get_history(request.session_id))
                    yield f"data: {json.dumps(payload)}\n\n"
                    return
            except Exception:
                pass
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
