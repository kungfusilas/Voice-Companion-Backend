from fastapi import APIRouter, Depends, HTTPException
from app.auth_middleware import verify_token
from app import proactive

router = APIRouter()


@router.get("/{user_id}/{companion_id}")
async def get_proactive_messages(
    user_id: str,
    companion_id: str,
    auth_user_id: str = Depends(verify_token),
):
    """
    Return all unread proactive messages (with optional activity payloads),
    then mark them as read.

    GET /api/proactive-messages/{user_id}/{companion_id}

    Requires a valid JWT. The authenticated user may only fetch their own messages.
    """
    if auth_user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    messages = await proactive.get_unread_messages(user_id, companion_id)
    if messages:
        await proactive.mark_messages_read(user_id, companion_id)
    return {
        "user_id": user_id,
        "companion_id": companion_id,
        "messages": messages,
        "count": len(messages),
    }
