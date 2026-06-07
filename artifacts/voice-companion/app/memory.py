"""
Supabase memory store.

Table schema (run once in Supabase SQL editor):

    create table if not exists memories (
        id          uuid primary key default gen_random_uuid(),
        user_id     text not null,
        persona_id  text not null,
        content     text not null,
        created_at  timestamptz not null default now()
    );

    create index on memories (user_id, persona_id, created_at desc);
"""
import os
from supabase import create_client, Client

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _client = create_client(url, key)
    return _client


async def save_memory(user_id: str, persona_id: str, content: str) -> dict:
    """Insert a single memory fact and return the created row."""
    client = _get_client()
    result = (
        client.table("memories")
        .insert({"user_id": user_id, "persona_id": persona_id, "content": content})
        .execute()
    )
    return result.data[0] if result.data else {}


async def fetch_memories(user_id: str, persona_id: str, limit: int = 10) -> list[dict]:
    """Return the `limit` most recent memories for a user+persona pair."""
    client = _get_client()
    result = (
        client.table("memories")
        .select("id, content, created_at")
        .eq("user_id", user_id)
        .eq("persona_id", persona_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


async def list_all_memories(user_id: str, persona_id: str) -> list[dict]:
    """Return all memories for the GET /api/memories endpoint."""
    client = _get_client()
    result = (
        client.table("memories")
        .select("id, content, created_at")
        .eq("user_id", user_id)
        .eq("persona_id", persona_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []
