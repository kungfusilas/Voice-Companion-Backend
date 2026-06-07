from fastapi import APIRouter, Query
from app import memory

router = APIRouter()


@router.get("")
async def get_memories(
    user_id: str = Query(..., description="User identifier"),
    persona_id: str = Query(..., description="Persona identifier"),
):
    """
    Return all stored memories for a given user + persona pair.
    GET /api/memories?user_id=<id>&persona_id=<id>
    """
    rows = await memory.list_all_memories(user_id, persona_id)
    return {"user_id": user_id, "persona_id": persona_id, "memories": rows, "count": len(rows)}
