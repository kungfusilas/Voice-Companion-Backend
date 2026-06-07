from fastapi import APIRouter, HTTPException
from app.models import SessionInfo
from app import store

router = APIRouter()


@router.get("", response_model=list[dict])
async def list_sessions():
    return store.list_sessions()


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    history = store.get_history(session_id)
    if not history and store.get_session_persona_id(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    persona_id = store.get_session_persona_id(session_id) or ""
    return SessionInfo(
        session_id=session_id,
        persona_id=persona_id,
        message_count=len(history),
        history=history,
    )


@router.delete("/{session_id}/history", status_code=204)
async def clear_session(session_id: str):
    if not store.clear_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
