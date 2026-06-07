import json
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.models import ChatMessage, ChatRequest, ChatResponse
from app import store, claude, venice_client
from app import memory as mem_store
from app import memory_extractor

router = APIRouter()

# Default user_id when no auth exists — single-user mode
_DEFAULT_USER = "default_user"


def _use_venice(persona_nsfw: bool, request_nsfw: bool) -> bool:
    return persona_nsfw or request_nsfw


async def _build_system_prompt_with_memory(persona, user_id: str) -> str:
    """Fetch recent memories and inject them into the persona's system prompt."""
    base_prompt = persona.build_system_prompt()
    try:
        memories = await mem_store.fetch_memories(user_id, persona.id, limit=10)
        memory_block = memory_extractor.format_memories_for_prompt(memories)
        return base_prompt + memory_block
    except Exception:
        # If Supabase is unreachable, fall back to base prompt
        return base_prompt


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")

    user_id = request.user_id or _DEFAULT_USER
    history = store.get_or_create_session(request.session_id, request.persona_id)
    system_prompt = await _build_system_prompt_with_memory(persona, user_id)
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

    # Extract memories asynchronously — don't block the response
    asyncio.create_task(
        memory_extractor.extract_and_save(user_id, persona.id, request.message, reply)
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

    Each event `data` field contains JSON:
        {"type": "token",  "text": "..."}
        {"type": "done",   "full_text": "...", "message_count": N, "model_backend": "claude"|"venice"}
        {"type": "error",  "message": "..."}
    """
    persona = store.get_persona(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona '{request.persona_id}' not found")

    user_id = request.user_id or _DEFAULT_USER
    history = store.get_or_create_session(request.session_id, request.persona_id)
    system_prompt = await _build_system_prompt_with_memory(persona, user_id)
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
                    # Extract memories in background after stream completes
                    asyncio.create_task(
                        memory_extractor.extract_and_save(user_id, persona.id, user_message, full_text)
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
