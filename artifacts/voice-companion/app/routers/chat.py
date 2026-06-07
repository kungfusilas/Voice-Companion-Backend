import json
import asyncio
from datetime import date
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.models import ChatMessage, ChatRequest, ChatResponse
from app import store, claude, venice_client
from app import memory as mem_store
from app import memory_extractor
from app import relationship

router = APIRouter()

_DEFAULT_USER = "default_user"


def _use_venice(persona_nsfw: bool, request_nsfw: bool) -> bool:
    return persona_nsfw or request_nsfw


def _inject_date(prompt: str) -> str:
    today = date.today().strftime("%B %d, %Y")
    return f"Today's date is {today}.\n\n{prompt}"


async def _build_system_prompt(persona, user_id: str, user_message: str) -> str:
    """
    Build the full system prompt:
    1. Base persona prompt + date injection
    2. Long-term memories (up to 10 recent)
    3. Emotionally relevant memories for this specific message
    4. Relationship level context
    """
    base_prompt = persona.build_system_prompt()
    try:
        # Fetch memories and message count in parallel
        memories, message_count = await asyncio.gather(
            mem_store.fetch_memories(user_id, persona.id, limit=30),
            relationship.get_message_count(user_id, persona.id),
        )

        # Standard recent memories block (most recent 10)
        memory_block = memory_extractor.format_memories_for_prompt(memories[:10])

        # Emotionally relevant memories surfaced for this specific message
        emotional_block = memory_extractor.format_emotional_memories_for_prompt(
            user_message, memories
        )

        # Relationship level
        rel_context = relationship.build_relationship_context(persona.id, message_count)

        return _inject_date(base_prompt + memory_block + emotional_block + rel_context)

    except Exception:
        return _inject_date(base_prompt)


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")

    user_id = request.user_id or _DEFAULT_USER
    history = store.get_or_create_session(request.session_id, request.persona_id)
    system_prompt = await _build_system_prompt(persona, user_id, request.message)
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

    # Fire-and-forget: memory extraction + relationship increment
    asyncio.create_task(
        memory_extractor.extract_and_save(user_id, persona.id, request.message, reply)
    )
    asyncio.create_task(
        relationship.increment_message_count(user_id, persona.id)
    )

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

    Each event data field contains JSON:
        {"type": "token",     "text": "..."}
        {"type": "searching", "query": "..."}
        {"type": "done",      "full_text": "...", "message_count": N, "model_backend": "..."}
        {"type": "error",     "message": "..."}
    """
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")

    user_id = request.user_id or _DEFAULT_USER
    history = store.get_or_create_session(request.session_id, request.persona_id)
    system_prompt = await _build_system_prompt(persona, user_id, request.message)
    use_venice = _use_venice(persona.nsfw_mode, request.nsfw_mode)

    store.append_message(request.session_id, ChatMessage(role="user", content=request.message))

    stream_fn = venice_client.stream_message if use_venice else claude.stream_message
    user_message = request.message

    async def event_generator():
        async for chunk in stream_fn(
            system_prompt=system_prompt,
            history=history,
            user_message=user_message,
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
                    # Fire-and-forget after stream completes
                    asyncio.create_task(
                        memory_extractor.extract_and_save(user_id, persona.id, user_message, full_text)
                    )
                    asyncio.create_task(
                        relationship.increment_message_count(user_id, persona.id)
                    )
                    return
            except Exception:
                pass
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
