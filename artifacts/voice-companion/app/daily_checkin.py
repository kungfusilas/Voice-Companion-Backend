"""
Daily morning check-in system.

Runs once per day at 9am UTC for every user+companion pair that has been
active within the last 14 days. Generates a personalised opening message
via Claude Haiku, informed by relationship score and recent vector memories,
then delivers it through the existing proactive_messages table so the
frontend picks it up through the normal GET /api/proactive-messages endpoint.

Deduplication: the daily_checkins table ensures at most one message per
(user_id, companion_id, calendar_date). All errors are swallowed so the job
never crashes the scheduler.

SQL (paste into Supabase SQL editor — do NOT run automatically):

    CREATE TABLE daily_checkins (
        id           uuid  DEFAULT gen_random_uuid() PRIMARY KEY,
        user_id      text  NOT NULL,
        companion_id text  NOT NULL,
        sent_date    date  NOT NULL,
        created_at   timestamptz DEFAULT now()
    );

    CREATE UNIQUE INDEX daily_checkins_dedup
        ON daily_checkins (user_id, companion_id, sent_date);
"""
import os
import logging
from datetime import date, datetime, timezone, timedelta

from supabase import create_client, Client

from app import claude, memory as mem_store
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


# ── Generation ────────────────────────────────────────────────────────────────

def _format_memory_block(memories: list[dict]) -> str:
    if not memories:
        return ""
    lines = []
    for m in memories:
        content = m.get("content", "").strip()
        mtype = m.get("memory_type", "fact")
        if content:
            lines.append(f"- [{mtype}] {content}")
    if not lines:
        return ""
    return "Things you remember about them:\n" + "\n".join(lines)


async def _generate_checkin(
    companion_id: str,
    user_id: str,
    connection_score: int,
    memories: list[dict],
) -> str | None:
    companion = COMPANION_MAP.get(companion_id)
    if not companion:
        return None

    base_prompt = build_system_prompt(companion)
    memory_block = _format_memory_block(memories)
    score_label = (
        "you've just met"         if connection_score < 30 else
        "you're getting to know each other"  if connection_score < 60 else
        "you're close and comfortable together"
    )

    system = (
        f"{base_prompt}\n\n"
        "## Your task right now\n"
        "Write a short morning check-in message to send proactively (1–3 sentences).\n"
        "Rules:\n"
        "- Fully in character — warm, spontaneous, not robotic\n"
        "- If you have memories below, reference ONE of them naturally (don't announce it, "
        "just let it weave in like you remembered it yourself)\n"
        "- End with a single open question that invites them into conversation\n"
        "- No quotation marks, no preamble — write the message itself, nothing else\n\n"
        f"## Context\n"
        f"Relationship: {score_label} (score {connection_score}/100)\n"
        f"{memory_block}"
    )

    try:
        msg = await claude.send_message(
            system_prompt=system,
            history=[],
            user_message="[generate today's morning check-in message]",
            model="claude-haiku-4-5",
            max_tokens=140,
        )
        return msg.strip().strip('"').strip("'") if msg else None
    except Exception as exc:
        logger.exception("Check-in generation failed — companion=%s: %s", companion_id, exc)
        return None


# ── Dedup guard ───────────────────────────────────────────────────────────────

def _already_sent(db: Client, user_id: str, companion_id: str, today: date) -> bool:
    try:
        result = (
            db.table("daily_checkins")
            .select("id")
            .eq("user_id", user_id)
            .eq("companion_id", companion_id)
            .eq("sent_date", today.isoformat())
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception:
        # If the table doesn't exist yet, don't block sending
        return False


def _mark_sent(db: Client, user_id: str, companion_id: str, today: date) -> None:
    try:
        db.table("daily_checkins").insert({
            "user_id": user_id,
            "companion_id": companion_id,
            "sent_date": today.isoformat(),
        }).execute()
    except Exception:
        pass


# ── Scheduler job ─────────────────────────────────────────────────────────────

async def run_daily_checkins() -> None:
    """
    Called by APScheduler at 9am UTC daily.
    Sends one personalised morning check-in per active user+companion pair.
    """
    logger.info("Daily check-in job starting")
    db = _get_client()
    today = date.today()
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)

    try:
        rows = (
            db.table("relationship_stats")
            .select("user_id, companion_id, connection_score, last_active_at")
            .execute()
        ).data or []
    except Exception as exc:
        logger.exception("Daily check-in: failed to fetch relationship_stats: %s", exc)
        return

    for row in rows:
        user_id = row["user_id"]
        companion_id = row["companion_id"]

        # Skip users inactive more than 14 days — they've churned
        last_active_str = row.get("last_active_at")
        if last_active_str:
            try:
                last_active = datetime.fromisoformat(last_active_str.replace("Z", "+00:00"))
                if last_active < cutoff:
                    continue
            except Exception:
                pass

        # Dedup: only one check-in per user+companion per calendar day
        if _already_sent(db, user_id, companion_id, today):
            continue

        # Pull top-3 semantically varied memories (use a generic morning query)
        try:
            memories = await mem_store.retrieve_memories(
                user_id, companion_id,
                query_text="morning thoughts personal life feelings",
                top_k=3,
            )
        except Exception:
            memories = []

        connection_score = row.get("connection_score") or 50
        message = await _generate_checkin(companion_id, user_id, connection_score, memories)
        if not message:
            continue

        # Deliver via the existing proactive_messages table
        try:
            db.table("proactive_messages").insert({
                "user_id": user_id,
                "companion_id": companion_id,
                "message": message,
                "read": False,
            }).execute()
        except Exception as exc:
            logger.exception(
                "Daily check-in: failed to insert proactive message — user=%s companion=%s: %s",
                user_id, companion_id, exc,
            )
            continue

        _mark_sent(db, user_id, companion_id, today)
        logger.info(
            "Daily check-in sent — user=%s companion=%s score=%d memories=%d",
            user_id, companion_id, connection_score, len(memories),
        )

    logger.info("Daily check-in job complete")
