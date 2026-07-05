from fastapi import APIRouter, Depends, HTTPException
from app.models import SessionInfo, ChatMessage
from app.auth_middleware import verify_token
from app import store, conversation_store

router = APIRouter()


@router.get("", response_model=list[dict])
async def list_sessions(user_id: str = Depends(verify_token)):
    return store.list_sessions_for_user(user_id)


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str, user_id: str = Depends(verify_token)):
    """
    B-H6 fix: owner=None is no longer treated as "skip check".

    Previous code:
        if owner is not None and owner != user_id: raise 403

    This silently skipped the ownership guard for sessions that existed in
    memory without an owner binding, allowing any authenticated user to read them.

    New logic:
        1. Fetch history + owner from in-memory store.
        2. If session is NOT in memory (no history, no persona) → check DB.
        3. If session IS in memory → require owner == user_id (None = mismatch → 403).
    """
    history = store.get_history(session_id)
    persona_id = store.get_session_persona_id(session_id) or ""

    if not history and not persona_id:
        # Not in memory (server restarted or session never started here).
        # Recover from Supabase archive — DB record carries authoritative ownership.
        info = await conversation_store.get_session_info(session_id)
        if info is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if info["user_id"] and info["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        recovered = [ChatMessage(role=m["role"], content=m["content"]) for m in info["messages"]]
        return SessionInfo(
            session_id=session_id,
            persona_id=info["companion_id"],
            message_count=len(recovered),
            history=recovered,
        )

    # Session is in memory.  Require an explicit owner match.
    # owner=None means the session has no registered owner → deny access.
    owner = store.get_session_owner(session_id)
    if owner != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return SessionInfo(
        session_id=session_id,
        persona_id=persona_id,
        message_count=len(history),
        history=history,
    )


@router.delete("/{session_id}/history", status_code=204)
async def clear_session(session_id: str, user_id: str = Depends(verify_token)):
    owner = store.get_session_owner(session_id)
    if owner != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if not store.clear_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
