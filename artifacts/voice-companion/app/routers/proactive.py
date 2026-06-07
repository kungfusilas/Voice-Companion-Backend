from fastapi import APIRouter
from app import proactive

router = APIRouter()


@router.get("/{user_id}/{companion_id}")
async def get_proactive_messages(user_id: str, companion_id: str):
    """
    Return all unread proactive messages for a user+companion pair,
    then mark them as read.

    GET /api/proactive-messages/{user_id}/{companion_id}
    """
    messages = await proactive.get_unread_messages(user_id, companion_id)
    if messages:
        await proactive.mark_messages_read(user_id, companion_id)
    return {
        "user_id": user_id,
        "companion_id": companion_id,
        "messages": messages,
        "count": len(messages),
    }
