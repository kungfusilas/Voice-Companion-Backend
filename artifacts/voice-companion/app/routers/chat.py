from fastapi import APIRouter, HTTPException
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
