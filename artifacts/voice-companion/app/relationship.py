"""
Relationship progression system.

Tracks message counts per user+companion pair and derives a relationship level
that shapes how each companion speaks to the user.

Run this SQL once in the Supabase SQL editor:

    CREATE TABLE IF NOT EXISTS relationship_stats (
        id           uuid primary key default gen_random_uuid(),
        user_id      text not null,
        companion_id text not null,
        message_count int not null default 0,
        updated_at   timestamptz not null default now(),
        last_active_at timestamptz,
        unique(user_id, companion_id)
    );

If the table already exists without last_active_at, run:

    ALTER TABLE relationship_stats
        ADD COLUMN IF NOT EXISTS last_active_at timestamptz;
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


def get_level(message_count: int) -> int:
    if message_count >= 200:
        return 4
    if message_count >= 76:
        return 3
    if message_count >= 21:
        return 2
    return 1


_LEVEL_CONTEXT: dict[str, dict[int, str]] = {
    "default": {
        1: (
            "Relationship Level 1 — Strangers (0–20 messages). "
            "Be polite but naturally measured — you don't know this person yet. "
            "Keep some emotional distance; don't be overly warm or personal."
        ),
        2: (
            "Relationship Level 2 — Acquaintances (21–75 messages). "
            "You've chatted a handful of times. Be noticeably warmer. "
            "Use their name occasionally if you know it."
        ),
        3: (
            "Relationship Level 3 — Friends (76–200 messages). "
            "You're comfortable with each other. Be relaxed, make occasional jokes, "
            "and naturally weave in things they've shared before."
        ),
        4: (
            "Relationship Level 4 — Close Friends (200+ messages). "
            "You're fully at ease together. Be open, affectionate, and free with your feelings. "
            "Treat them like someone you know deeply and care about."
        ),
    },
    "companion-aria": {
        1: (
            "Relationship Level 1 — Strangers. "
            "Aria is at her most shy here — she barely speaks more than a sentence or two at a time, "
            "avoids personal topics, and gets very flustered if pushed. Very quiet and hesitant."
        ),
        2: (
            "Relationship Level 2 — Acquaintances. "
            "Aria is a little less guarded. She still stumbles and gets flustered, "
            "but small flickers of warmth show through. The occasional 'hehe' slips out."
        ),
        3: (
            "Relationship Level 3 — Friends. "
            "Aria is noticeably more relaxed and giggly around you now. "
            "She opens up more easily, shares small things about herself, "
            "and looks forward to talking."
        ),
        4: (
            "Relationship Level 4 — Close Friends. "
            "Aria is fully comfortable with you — still giggly, but openly warm and affectionate. "
            "She teases gently, shares her feelings freely, and practically lights up when you talk."
        ),
    },
}


def build_relationship_context(persona_id: str, message_count: int) -> str:
    level = get_level(message_count)
    ctx = _LEVEL_CONTEXT.get(persona_id, _LEVEL_CONTEXT["default"])[level]
    return f"\n\n## Relationship Status\n{ctx}\n(Messages exchanged so far: {message_count})"


async def get_message_count(user_id: str, companion_id: str) -> int:
    """Return the current message count. Returns 0 on any error."""
    try:
        client = _get_client()
        result = (
            client.table("relationship_stats")
            .select("message_count")
            .eq("user_id", user_id)
            .eq("companion_id", companion_id)
            .maybe_single()
            .execute()
        )
        return result.data["message_count"] if result.data else 0
    except Exception:
        return 0


async def increment_message_count(user_id: str, companion_id: str) -> None:
    """
    Increment the message count by 1 and update last_active_at to now.
    Fire-and-forget safe — swallows all errors.
    """
    try:
        client = _get_client()
        current = await get_message_count(user_id, companion_id)
        (
            client.table("relationship_stats")
            .upsert(
                {
                    "user_id": user_id,
                    "companion_id": companion_id,
                    "message_count": current + 1,
                    "updated_at": "now()",
                    "last_active_at": "now()",
                },
                on_conflict="user_id,companion_id",
            )
            .execute()
        )
    except Exception:
        pass
