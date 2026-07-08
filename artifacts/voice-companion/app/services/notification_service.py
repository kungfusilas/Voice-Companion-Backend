"""
APScheduler notification jobs.

Three scheduled jobs:
  1. send_daily_question_notifications()   — hourly, fires for users whose local clock
                                             is 09:00 (based on their stored timezone offset).
  2. send_weekly_question_set_notifications() — Monday 09:00 UTC, sends the week's
                                             themed question set to all push subscribers.
  3. send_reengagement_notifications()    — daily 09:10 UTC, nudges users who haven't
                                             opened the app in 7+ days.

Import and schedule from app/main.py lifespan.
"""
import logging
import os
from datetime import datetime, timezone, timedelta

import httpx

from app.push_sender import send_push_to_user
from app.services.question_bank import get_daily_question, get_weekly_question_set

logger = logging.getLogger(__name__)


def _supabase_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _supabase_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def _fetch_all_push_subscribers() -> list[dict]:
    """Fetch all push subscriptions from Supabase (distinct user_id rows)."""
    url = _supabase_url()
    if not url:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/push_subscriptions",
                params={"select": "user_id,timezone_offset_hours"},
                headers=_supabase_headers(),
            )
        if resp.status_code != 200:
            logger.warning("push_subs fetch failed status=%s", resp.status_code)
            return []
        rows = resp.json()
        # Deduplicate by user_id, keeping earliest timezone_offset_hours per user
        seen: dict[str, int] = {}
        for row in rows:
            uid = row.get("user_id")
            if uid and uid not in seen:
                seen[uid] = int(row.get("timezone_offset_hours") or 0)
        return [{"user_id": uid, "timezone_offset_hours": tz} for uid, tz in seen.items()]
    except Exception as exc:
        logger.warning("_fetch_all_push_subscribers error: %s", exc)
        return []


async def _fetch_inactive_user_ids(inactive_days: int = 7) -> list[str]:
    """Return user_ids who have push subscriptions but no conversation in N days."""
    url = _supabase_url()
    if not url:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=inactive_days)).isoformat()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Get all subscribed users
            sub_resp = await client.get(
                f"{url}/rest/v1/push_subscriptions",
                params={"select": "user_id"},
                headers=_supabase_headers(),
            )
            if sub_resp.status_code != 200:
                return []
            all_subs = {row["user_id"] for row in sub_resp.json() if row.get("user_id")}

            # Get users who have been active recently (conversations after cutoff)
            active_resp = await client.get(
                f"{url}/rest/v1/conversations",
                params={
                    "select": "user_id",
                    "created_at": f"gt.{cutoff}",
                },
                headers=_supabase_headers(),
            )
            active_users = set()
            if active_resp.status_code == 200:
                active_users = {row["user_id"] for row in active_resp.json() if row.get("user_id")}

        inactive = list(all_subs - active_users)
        return inactive
    except Exception as exc:
        logger.warning("_fetch_inactive_user_ids error: %s", exc)
        return []


# ── Job 1: Hourly — daily question at local 9am ───────────────────────────────

async def send_daily_question_notifications() -> None:
    """
    Runs every hour. Sends the daily question to users whose local time is
    currently between 09:00 and 09:59.
    """
    current_utc_hour = datetime.now(timezone.utc).hour
    subscribers = await _fetch_all_push_subscribers()

    sent = 0
    for sub in subscribers:
        tz_offset = sub.get("timezone_offset_hours", 0) or 0
        local_hour = (current_utc_hour + tz_offset) % 24
        if local_hour != 9:
            continue

        user_id = sub["user_id"]
        try:
            q = get_daily_question(user_id)
            n = await send_push_to_user(
                user_id=user_id,
                title="Today's question from AEVA 💭",
                body=q["question"],
                data={"type": "daily_question", "question": q["question"], "url": "/"},
                icon="/icon-192.png",
            )
            sent += n
        except Exception as exc:
            logger.warning("daily_question push failed user=%s: %s", user_id, exc)

    if sent:
        logger.info("daily_question notifications sent=%d", sent)


# ── Job 2: Monday 9am UTC — weekly question set ───────────────────────────────

async def send_weekly_question_set_notifications() -> None:
    """
    Runs Monday 09:00 UTC. Sends the week's themed question set to all subscribers.
    """
    weekly = get_weekly_question_set()
    preview = weekly["questions"][0] if weekly["questions"] else ""
    body = f'This week\'s theme: "{weekly["theme"]}" — {preview[:80]}…'

    subscribers = await _fetch_all_push_subscribers()
    sent = 0
    for sub in subscribers:
        user_id = sub["user_id"]
        try:
            n = await send_push_to_user(
                user_id=user_id,
                title=f"This week: {weekly['theme']} ✨",
                body=body,
                data={"type": "weekly_set", "theme": weekly["theme"], "url": "/"},
            )
            sent += n
        except Exception as exc:
            logger.warning("weekly_set push failed user=%s: %s", user_id, exc)

    logger.info("weekly_set notifications sent=%d theme=%s", sent, weekly["theme"])


# ── Job 3: Daily 9:10am UTC — re-engagement ──────────────────────────────────

async def send_reengagement_notifications() -> None:
    """
    Runs daily 09:10 UTC. Nudges users who haven't had a conversation in 7+ days.
    """
    inactive_ids = await _fetch_inactive_user_ids(inactive_days=7)
    if not inactive_ids:
        return

    messages = [
        ("AEVA misses you 💙", "It's been a while. What's been on your mind lately?"),
        ("A question for you 🌿", "Life moves fast. Want to slow down and reflect for a minute?"),
        ("Checking in ✨", "You've been on AEVA's mind. How are you really doing?"),
        ("Come back when you're ready 🕊️", "No pressure — just know there's space here whenever you need it."),
    ]

    sent = 0
    for i, user_id in enumerate(inactive_ids):
        title, body = messages[i % len(messages)]
        try:
            n = await send_push_to_user(
                user_id=user_id,
                title=title,
                body=body,
                data={"type": "reengagement", "url": "/"},
            )
            sent += n
        except Exception as exc:
            logger.warning("reengagement push failed user=%s: %s", user_id, exc)

    logger.info("reengagement notifications sent=%d users=%d", sent, len(inactive_ids))
