"""
Relationship progression system.

Tracks message counts, connection scores, and drift state per user+companion pair.

Full schema (already applied via migration):

    CREATE TABLE IF NOT EXISTS relationship_stats (
        id                    uuid primary key default gen_random_uuid(),
        user_id               text not null,
        companion_id          text not null,
        message_count         int not null default 0,
        updated_at            timestamptz not null default now(),
        last_active_at        timestamptz,
        relationship_type     text,
        connection_score      integer default 50,
        drift_flag            boolean default false,
        drift_acknowledged_at timestamptz,
        last_scored_at        timestamptz,
        unique(user_id, companion_id)
    );
"""
import os
import re
from supabase import create_client, Client

_client: Client | None = None

_FUNCTIONAL_RE = re.compile(
    r"^(search|find|look up|tell me|what is|what are|who is|who are|when |where |how do|how to|"
    r"explain|define|give me|show me|list|summarize|translate|calculate|convert|"
    r"weather|news|score|price|recipe|directions)",
    re.IGNORECASE,
)


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _client = create_client(url, key)
    return _client


def _defaults(user_id: str, companion_id: str) -> dict:
    return {
        "user_id": user_id,
        "companion_id": companion_id,
        "message_count": 0,
        "relationship_type": None,
        "connection_score": 50,
        "drift_flag": False,
        "drift_acknowledged_at": None,
        "last_scored_at": None,
        "last_active_at": None,
    }


# ── Read ──────────────────────────────────────────────────────────────────────

async def get_stats(user_id: str, companion_id: str) -> dict:
    """Return the full row for this user+companion pair. Returns defaults if missing."""
    try:
        result = (
            _get_client()
            .table("relationship_stats")
            .select("*")
            .eq("user_id", user_id)
            .eq("companion_id", companion_id)
            .maybe_single()
            .execute()
        )
        return result.data if result.data else _defaults(user_id, companion_id)
    except Exception:
        return _defaults(user_id, companion_id)


async def get_message_count(user_id: str, companion_id: str) -> int:
    """Return the current message count. Returns 0 on any error."""
    stats = await get_stats(user_id, companion_id)
    return stats.get("message_count", 0)


async def needs_drift_inject(user_id: str, companion_id: str) -> bool:
    """True if drift_flag=True AND drift_acknowledged_at IS NULL."""
    try:
        stats = await get_stats(user_id, companion_id)
        return bool(stats.get("drift_flag")) and stats.get("drift_acknowledged_at") is None
    except Exception:
        return False


# ── Write ─────────────────────────────────────────────────────────────────────

async def upsert_relationship_type(user_id: str, companion_id: str, rel_type: str) -> None:
    """Set the relationship type. Preserves connection_score if row already exists."""
    try:
        _get_client().table("relationship_stats").upsert(
            {
                "user_id": user_id,
                "companion_id": companion_id,
                "relationship_type": rel_type,
                "updated_at": "now()",
            },
            on_conflict="user_id,companion_id",
        ).execute()
    except Exception:
        pass


async def apply_score_delta(user_id: str, companion_id: str, delta: int) -> int:
    """Add delta to connection_score (clamped 0-100). Returns the new score."""
    try:
        stats = await get_stats(user_id, companion_id)
        current = stats.get("connection_score") or 50
        new_score = max(0, min(100, current + delta))
        _get_client().table("relationship_stats").upsert(
            {
                "user_id": user_id,
                "companion_id": companion_id,
                "connection_score": new_score,
                "last_scored_at": "now()",
                "updated_at": "now()",
            },
            on_conflict="user_id,companion_id",
        ).execute()
        return new_score
    except Exception:
        return 50


async def increment_message_count(user_id: str, companion_id: str) -> None:
    """Increment message_count by 1 and update last_active_at. Fire-and-forget safe."""
    try:
        current = await get_message_count(user_id, companion_id)
        _get_client().table("relationship_stats").upsert(
            {
                "user_id": user_id,
                "companion_id": companion_id,
                "message_count": current + 1,
                "updated_at": "now()",
                "last_active_at": "now()",
            },
            on_conflict="user_id,companion_id",
        ).execute()
    except Exception:
        pass


async def mark_drift(user_id: str, companion_id: str) -> None:
    """Set drift_flag=True (does NOT set drift_acknowledged_at)."""
    try:
        _get_client().table("relationship_stats").upsert(
            {
                "user_id": user_id,
                "companion_id": companion_id,
                "drift_flag": True,
                "updated_at": "now()",
            },
            on_conflict="user_id,companion_id",
        ).execute()
    except Exception:
        pass


async def acknowledge_drift(user_id: str, companion_id: str) -> None:
    """Set drift_acknowledged_at=now() so the drift message never repeats."""
    try:
        _get_client().table("relationship_stats").upsert(
            {
                "user_id": user_id,
                "companion_id": companion_id,
                "drift_acknowledged_at": "now()",
                "updated_at": "now()",
            },
            on_conflict="user_id,companion_id",
        ).execute()
    except Exception:
        pass


# ── Drift detection ───────────────────────────────────────────────────────────

def check_drift_condition(user_messages: list[str]) -> bool:
    """
    Returns True if >70% of the last 30 user messages look like functional/task requests
    rather than personal/emotional conversation.
    Requires at least 5 messages to trigger.
    """
    if len(user_messages) < 5:
        return False
    recent = user_messages[-30:]
    functional = sum(1 for m in recent if _FUNCTIONAL_RE.match(m.strip()))
    return functional / len(recent) > 0.7


# ── System-prompt context ─────────────────────────────────────────────────────

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
            "avoids personal topics, and gets very flustered if pushed."
        ),
        2: (
            "Relationship Level 2 — Acquaintances. "
            "Aria is a little less guarded. She still stumbles and gets flustered, "
            "but small flickers of warmth show through."
        ),
        3: (
            "Relationship Level 3 — Friends. "
            "Aria is noticeably more relaxed and giggly around you now. "
            "She opens up more easily and looks forward to talking."
        ),
        4: (
            "Relationship Level 4 — Close Friends. "
            "Aria is fully comfortable with you — still giggly, but openly warm and affectionate. "
            "She teases gently and practically lights up when you talk."
        ),
    },
}


def build_relationship_context(persona_id: str, message_count: int) -> str:
    level = get_level(message_count)
    ctx = _LEVEL_CONTEXT.get(persona_id, _LEVEL_CONTEXT["default"])[level]
    return f"\n\n## Relationship Status\n{ctx}\n(Messages exchanged so far: {message_count})"
