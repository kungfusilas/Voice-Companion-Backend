"""
Weekly Relationship-Building Ritual.

Checks whether a ritual session is due for a user+companion pair (>= 7 days
since the last one, or never done).  When due, records the session immediately
(so the 7-day cooldown starts) and returns a curated set of 3-4 questions from
a rotating bank, skipping anything that feels already-covered by existing
memories (heuristic keyword match — no LLM call).

New table required (user creates in Supabase):
    CREATE TABLE IF NOT EXISTS public.relationship_sessions (
        id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id      text        NOT NULL,
        companion_id text        NOT NULL,
        session_type text        NOT NULL DEFAULT 'ritual',
        created_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS relationship_sessions_user_companion_time
        ON public.relationship_sessions (user_id, companion_id, created_at DESC);
"""
from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_COOLDOWN_DAYS = 7

# ── Question bank ──────────────────────────────────────────────────────────────

_ALL_QUESTIONS: list[dict] = [
    {"id": "q_goal",       "text": "What's a goal you're working toward at the moment?",              "skip_keyword": "goal"},
    {"id": "q_people",     "text": "Who are the most important people in your life right now?",        "skip_keyword": "family"},
    {"id": "q_joy",        "text": "What's been bringing you the most joy lately?",                   "skip_keyword": "joy"},
    {"id": "q_proud",      "text": "What's something you're proud of from the past month?",           "skip_keyword": "proud"},
    {"id": "q_tough",      "text": "Is there anything you've been finding tough lately?",             "skip_keyword": "struggle"},
    {"id": "q_good_day",   "text": "What does a good day look like for you right now?",               "skip_keyword": None},
    {"id": "q_forward",    "text": "What's something you're looking forward to?",                     "skip_keyword": "looking forward"},
    {"id": "q_matters",    "text": "What matters most to you these days?",                            "skip_keyword": "matters most"},
    {"id": "q_rel",        "text": "Is there a relationship in your life you'd like to work on?",     "skip_keyword": "relationship"},
    {"id": "q_win",        "text": "What's a recent win — big or small — you haven't fully celebrated?", "skip_keyword": "win"},
    {"id": "q_curious",    "text": "What's something new you've been curious about or exploring?",    "skip_keyword": "curious"},
    {"id": "q_week_win",   "text": "What would make this week feel like a success to you?",           "skip_keyword": None},
    {"id": "q_support",    "text": "Who do you go to when you need support?",                         "skip_keyword": "support"},
    {"id": "q_understood", "text": "What's something you wish people knew about you?",               "skip_keyword": "understood"},
    {"id": "q_learning",   "text": "What are you learning about yourself lately?",                    "skip_keyword": "learning"},
]


# ── Supabase helpers ───────────────────────────────────────────────────────────

def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def _latest_session_date(user_id: str, companion_id: str) -> datetime | None:
    """Return the created_at of the most recent ritual session, or None."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            resp = await http.get(
                f"{_sb_url()}/rest/v1/relationship_sessions",
                headers=_sb_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "companion_id": f"eq.{companion_id}",
                    "session_type": "eq.ritual",
                    "order": "created_at.desc",
                    "limit": "1",
                    "select": "created_at",
                },
            )
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                raw = rows[0]["created_at"]
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception as exc:
        logger.debug("[ritual] _latest_session_date error: %r", exc)
    return None


async def _record_session(user_id: str, companion_id: str) -> None:
    """Insert a ritual session row (records the 7-day cooldown start)."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            await http.post(
                f"{_sb_url()}/rest/v1/relationship_sessions",
                headers={**_sb_headers(), "Prefer": "return=minimal"},
                json={"user_id": user_id, "companion_id": companion_id, "session_type": "ritual"},
            )
        logger.debug("[ritual] session recorded for user=%s companion=%s", user_id[:8], companion_id)
    except Exception as exc:
        logger.debug("[ritual] _record_session error: %r", exc)


async def _memory_keywords(user_id: str, companion_id: str) -> set[str]:
    """Fetch a sample of recent memory content to check what's already known."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            resp = await http.get(
                f"{_sb_url()}/rest/v1/memories",
                headers=_sb_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "companion_id": f"eq.{companion_id}",
                    "order": "created_at.desc",
                    "limit": "20",
                    "select": "content",
                },
            )
        if resp.status_code == 200:
            combined = " ".join(r.get("content", "") for r in resp.json()).lower()
            return set(combined.split())
    except Exception as exc:
        logger.debug("[ritual] _memory_keywords error: %r", exc)
    return set()


def _select_questions(memory_words: set[str], n: int = 3) -> list[str]:
    """
    Pick n questions from the bank, skipping any whose skip_keyword already
    appears in recent memory content.  Falls back to random selection if not
    enough non-skipped candidates exist.
    """
    candidates = []
    skipped = []
    shuffled = list(_ALL_QUESTIONS)
    random.shuffle(shuffled)

    for q in shuffled:
        kw = q.get("skip_keyword")
        if kw and kw in memory_words:
            skipped.append(q["text"])
        else:
            candidates.append(q["text"])

    chosen = candidates[:n]
    # If we didn't get enough, fill from skipped ones
    if len(chosen) < n:
        chosen += skipped[: n - len(chosen)]

    return chosen[:n]


# ── Public API ─────────────────────────────────────────────────────────────────

async def check_ritual_due(user_id: str, companion_id: str) -> dict:
    """
    Returns {due: bool, questions: list[str] | None}.

    When due=True:
    - A new session row is recorded immediately (starts the 7-day cooldown).
    - 3 questions are selected, skipping topics already in memory.

    Fails gracefully: if the relationship_sessions table doesn't exist yet,
    returns {due: False} so the app continues normally.
    """
    try:
        latest = await _latest_session_date(user_id, companion_id)
        now = datetime.now(timezone.utc)

        if latest is not None:
            age = now - latest
            if age < timedelta(days=_COOLDOWN_DAYS):
                return {"due": False, "questions": None}

        # Due — record session NOW (regardless of user response, cooldown starts)
        await _record_session(user_id, companion_id)

        memory_words = await _memory_keywords(user_id, companion_id)
        questions = _select_questions(memory_words, n=3)

        logger.info("[ritual] ritual due for user=%s companion=%s", user_id[:8], companion_id)
        return {"due": True, "questions": questions}

    except Exception as exc:
        logger.warning("[ritual] check_ritual_due error (failing open): %r", exc)
        return {"due": False, "questions": None}
