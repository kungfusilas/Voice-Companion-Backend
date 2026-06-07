from fastapi import APIRouter, Depends, Query
from app import memory
from app.auth_middleware import verify_token

router = APIRouter()


@router.get("")
async def get_memories(
    persona_id: str = Query(..., description="Persona identifier"),
    user_id: str = Depends(verify_token),
):
    """
    Return all stored memories for the authenticated user + persona pair.
    GET /api/memories?persona_id=<id>
    user_id is sourced from the Bearer JWT — no longer accepted as a query param.
    """
    rows = await memory.list_all_memories(user_id, persona_id)
    return {"user_id": user_id, "persona_id": persona_id, "memories": rows, "count": len(rows)}
