"""
Proactive messaging system.

Checks for user+companion pairs that have been inactive for 20+ hours and
saves a short in-character message to Supabase for in-app delivery.

SQL to run once in Supabase:

    -- Add last_active_at to relationship_stats (if not done yet)
    ALTER TABLE relationship_stats
        ADD COLUMN IF NOT EXISTS last_active_at timestamptz;

    -- Proactive messages table
    CREATE TABLE IF NOT EXISTS proactive_messages (
        id           uuid primary key default gen_random_uuid(),
        user_id      text not null,
        companion_id text not null,
        message      text not null,
        sent_at      timestamptz not null default now(),
        read         bool not null default false
    );

    CREATE INDEX IF NOT EXISTS proactive_messages_lookup
        ON proactive_messages (user_id, companion_id, read, sent_at DESC);
"""
import os
import logging
from datetime import datetime, timezone, timedelta

from supabase import create_client, Client

from app import claude
from app.companions import COMPANION_MAP, build_system_prompt

logger = logging.getLogger(__name__)

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


def _parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


async def _generate_message(companion_id: str) -> str | None:
    companion = COMPANION_MAP.get(companion_id)
    if not companion:
        return None
    base_prompt = build_system_prompt(companion)
    system = (
        f"{base_prompt}\n\n"
        "The user hasn't been online for a while. Write a short proactive check-in message "
        "(1–3 sentences) fully in character — warm but not desperate, like a genuine thought "
        "that crossed your mind while they were away. Do NOT use quotation marks around the "
        "message. Just write the message itself, nothing else."
    )
    try:
        return await claude.send_message(
            system_prompt=system,
            history=[],
            user_message="[generate a proactive check-in message for this user who has been away]",
            model="claude-haiku-4-5",
            max_tokens=120,
        )
    except Exception as exc:
        logger.exception("Message generation failed for %s: %s", companion_id, exc)
        return None


async def check_and_send_proactive_messages() -> None:
    """
    Main scheduler job. Finds inactive user+companion pairs and saves
    an in-character check-in message to the proactive_messages table.
    """
    logger.info("Proactive message check starting")
    try:
        db = _get_client()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=20)
        since_24h = (now - timedelta(hours=24)).isoformat()

        stats_result = (
            db.table("relationship_stats")
            .select("user_id, companion_id, last_active_at, updated_at")
            .execute()
        )
        rows = stats_result.data or []

        for row in rows:
            user_id = row["user_id"]
            companion_id = row["companion_id"]

            last_active = _parse_ts(row.get("last_active_at")) or _parse_ts(row.get("updated_at"))
            if last_active is None or last_active > cutoff:
                continue

            recent = (
                db.table("proactive_messages")
                .select("id")
                .eq("user_id", user_id)
                .eq("companion_id", companion_id)
                .gte("sent_at", since_24h)
                .limit(1)
                .execute()
            )
            if recent.data:
                continue

            message = await _generate_message(companion_id)
            if not message:
                continue

            message = message.strip().strip('"').strip("'")

            db.table("proactive_messages").insert({
                "user_id": user_id,
                "companion_id": companion_id,
                "message": message,
                "read": False,
            }).execute()

            logger.info("Proactive message saved — user=%s companion=%s", user_id, companion_id)

    except Exception as exc:
        logger.exception("Proactive check failed: %s", exc)


async def get_unread_messages(user_id: str, companion_id: str) -> list[dict]:
    """Return all unread proactive messages for a user+companion pair."""
    try:
        db = _get_client()
        result = (
            db.table("proactive_messages")
            .select("id, message, sent_at")
            .eq("user_id", user_id)
            .eq("companion_id", companion_id)
            .eq("read", False)
            .order("sent_at", desc=False)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


async def mark_messages_read(user_id: str, companion_id: str) -> None:
    """Mark all unread messages for this pair as read."""
    try:
        db = _get_client()
        (
            db.table("proactive_messages")
            .update({"read": True})
            .eq("user_id", user_id)
            .eq("companion_id", companion_id)
            .eq("read", False)
            .execute()
        )
    except Exception:
        pass
