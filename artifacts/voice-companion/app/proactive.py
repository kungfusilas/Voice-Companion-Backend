"""
Proactive messaging system.

Two jobs run on a schedule:
1. check_and_send_proactive_messages — every hour, sends a check-in for users idle 20+ hours
2. check_and_send_daily_activity     — every hour, sends one activity per user per day

SQL (already applied via migration):

    CREATE TABLE IF NOT EXISTS proactive_messages (
        id            uuid primary key default gen_random_uuid(),
        user_id       text not null,
        companion_id  text not null,
        message       text not null,
        sent_at       timestamptz not null default now(),
        read          bool not null default false,
        activity_type text,
        activity_data jsonb
    );

    ALTER TABLE relationship_stats
        ADD COLUMN IF NOT EXISTS last_activity_sent_at timestamptz;
"""
import os
import random
import logging
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException
from supabase import create_client, Client

from app import claude
from app import activities as act_core
from app.companions import COMPANION_MAP, build_system_prompt
from app.usage import get_user_tier, check_message_quota

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


# ── Check-in messages ─────────────────────────────────────────────────────────

async def _generate_checkin(companion_id: str) -> str | None:
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
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
        )
    except Exception as exc:
        logger.exception("Check-in generation failed for %s: %s", companion_id, exc)
        return None


async def check_and_send_proactive_messages() -> None:
    """Hourly job: check-in for users idle 20+ hours (max once per 24h)."""
    logger.info("Proactive message check starting")
    try:
        db = _get_client()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=20)
        since_24h = (now - timedelta(hours=24)).isoformat()

        rows = (
            db.table("relationship_stats")
            .select("user_id, companion_id, last_active_at, updated_at")
            .execute()
        ).data or []

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

            message = await _generate_checkin(companion_id)
            if not message:
                continue

            message = message.strip().strip('"').strip("'")

            # Paid-tier gate + quota deduction (free users get no proactive messages)
            try:
                tier, _ = await get_user_tier(user_id)
                if tier not in ("basic", "premium", "power", "elite"):
                    continue
                await check_message_quota(user_id, tier, None)
            except HTTPException:
                logger.info("Proactive check-in skipped — quota reached user=%s", user_id)
                continue
            except Exception as exc:
                logger.warning("Quota check error user=%s: %s", user_id, exc)
                continue

            db.table("proactive_messages").insert({
                "user_id": user_id,
                "companion_id": companion_id,
                "message": message,
                "read": False,
            }).execute()

            logger.info("Check-in saved — user=%s companion=%s", user_id, companion_id)

    except Exception as exc:
        logger.exception("Proactive check failed: %s", exc)


# ── Daily activity ────────────────────────────────────────────────────────────

_ACTIVITY_TYPES = ["word_game", "trivia", "would_you_rather"]


async def check_and_send_daily_activity() -> None:
    """Hourly job: send one random activity per user+companion pair per day."""
    logger.info("Daily activity check starting")
    try:
        db = _get_client()
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days_ago = now - timedelta(days=7)

        rows = (
            db.table("relationship_stats")
            .select("user_id, companion_id, last_active_at")
            .execute()
        ).data or []

        for row in rows:
            user_id = row["user_id"]
            companion_id = row["companion_id"]

            # Only for users active within the last 7 days
            last_active = _parse_ts(row.get("last_active_at"))
            if not last_active or last_active < seven_days_ago:
                continue

            activity_type = random.choice(_ACTIVITY_TYPES)
            try:
                data = await act_core.generate_activity(companion_id, activity_type)
            except Exception as exc:
                logger.exception("Activity generation failed — user=%s: %s", user_id, exc)
                continue

            intro = data.get("companion_intro", "")

            # Paid-tier gate + quota deduction (free users get no proactive activities)
            try:
                tier, _ = await get_user_tier(user_id)
                if tier not in ("basic", "premium", "power", "elite"):
                    continue
                await check_message_quota(user_id, tier, None)
            except HTTPException:
                logger.info("Daily activity skipped — quota reached user=%s", user_id)
                continue
            except Exception as exc:
                logger.warning("Quota check error user=%s: %s", user_id, exc)
                continue

            db.table("proactive_messages").insert({
                "user_id": user_id,
                "companion_id": companion_id,
                "message": intro,
                "read": False,
                "activity_type": activity_type,
                "activity_data": data,
            }).execute()

            db.table("relationship_stats").upsert(
                {
                    "user_id": user_id,
                    "companion_id": companion_id,
                    "updated_at": "now()",
                },
                on_conflict="user_id,companion_id",
            ).execute()

            logger.info(
                "Daily activity saved — user=%s companion=%s type=%s",
                user_id, companion_id, activity_type,
            )

    except Exception as exc:
        logger.exception("Daily activity check failed: %s", exc)


# ── Read / mark-read ──────────────────────────────────────────────────────────

async def get_unread_messages(user_id: str, companion_id: str) -> list[dict]:
    """Return all unread proactive messages (including activity payloads)."""
    try:
        db = _get_client()
        result = (
            db.table("proactive_messages")
            .select("id, message, sent_at, activity_type, activity_data")
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
