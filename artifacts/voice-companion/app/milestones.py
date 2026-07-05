"""
Companion Growth System — milestone definitions, evaluation, and persistence.

Milestones are computed from existing tables (memories, goals, weekly_reports,
legacy_chapters, relationship_stats, bond_scores) plus the new relationship_sessions
table (from the ritual feature).  Every query is wrapped in try/except — a missing
table or Supabase error silently returns 0, so the endpoint never hard-fails.

New table required (user creates in Supabase):
    CREATE TABLE IF NOT EXISTS public.user_milestones (
        id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id      text        NOT NULL,
        companion_id text        NOT NULL,
        milestone_id text        NOT NULL,
        unlocked_at  timestamptz NOT NULL DEFAULT now(),
        seen_at      timestamptz,
        UNIQUE(user_id, companion_id, milestone_id)
    );
    CREATE INDEX IF NOT EXISTS user_milestones_user_companion
        ON public.user_milestones (user_id, companion_id);
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Milestone catalogue ────────────────────────────────────────────────────────

MILESTONE_DEFS: list[dict] = [
    # Memory milestones
    {
        "id": "first_memory",
        "title": "First Memory",
        "description": "Your companion saved their first memory about you",
        "icon": "🧠",
        "category": "memory",
        "threshold": 1,
    },
    {
        "id": "memories_10",
        "title": "Knows You Well",
        "description": "10 memories saved",
        "icon": "📚",
        "category": "memory",
        "threshold": 10,
    },
    {
        "id": "memories_25",
        "title": "Knows You Inside Out",
        "description": "25 memories saved",
        "icon": "💡",
        "category": "memory",
        "threshold": 25,
    },
    {
        "id": "memories_50",
        "title": "Deeply Known",
        "description": "50 memories saved",
        "icon": "✨",
        "category": "memory",
        "threshold": 50,
    },
    # Goal milestones
    {
        "id": "first_goal",
        "title": "First Goal",
        "description": "You shared your first goal",
        "icon": "🎯",
        "category": "goal",
        "threshold": 1,
    },
    {
        "id": "goals_5",
        "title": "Goal Setter",
        "description": "5 goals tracked",
        "icon": "📋",
        "category": "goal",
        "threshold": 5,
    },
    {
        "id": "goals_10",
        "title": "Goal Crusher",
        "description": "10 goals tracked",
        "icon": "🏆",
        "category": "goal",
        "threshold": 10,
    },
    # Ritual / reflection milestones
    {
        "id": "first_reflection",
        "title": "First Reflection",
        "description": "First weekly check-in completed",
        "icon": "🌙",
        "category": "ritual",
        "threshold": 1,
    },
    {
        "id": "reflections_4",
        "title": "Monthly Ritual",
        "description": "4 weekly check-ins completed",
        "icon": "🌕",
        "category": "ritual",
        "threshold": 4,
    },
    # Legacy chapter milestone
    {
        "id": "first_chapter",
        "title": "First Chapter",
        "description": "First legacy chapter written",
        "icon": "📖",
        "category": "chapter",
        "threshold": 1,
    },
    # Time together milestones
    {
        "id": "one_week",
        "title": "One Week Together",
        "description": "7 days since you first connected",
        "icon": "🗓️",
        "category": "time",
        "threshold": 7,
    },
    {
        "id": "one_month",
        "title": "One Month Together",
        "description": "30 days since you first connected",
        "icon": "🎂",
        "category": "time",
        "threshold": 30,
    },
    # Bond-level milestones
    {
        "id": "bond_warm",
        "title": "Warm Connection",
        "description": "Bond score reached 25",
        "icon": "🌱",
        "category": "bond",
        "threshold": 25,
    },
    {
        "id": "bond_close",
        "title": "Close Bond",
        "description": "Bond score reached 65",
        "icon": "💙",
        "category": "bond",
        "threshold": 65,
    },
    {
        "id": "bond_closest",
        "title": "Closest Friends",
        "description": "Bond score reached 85",
        "icon": "💜",
        "category": "bond",
        "threshold": 85,
    },
]

_MILESTONE_IDS = {m["id"] for m in MILESTONE_DEFS}


# ── Supabase helpers ───────────────────────────────────────────────────────────

def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_headers(prefer_repr: bool = False) -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    h: dict[str, str] = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer_repr:
        h["Prefer"] = "return=representation"
    return h


async def _count(table: str, params: dict[str, str]) -> int:
    """Return row count for the given table+params.  Returns 0 on any error."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            resp = await http.get(
                f"{_sb_url()}/rest/v1/{table}",
                headers={**_sb_headers(), "Prefer": "count=exact"},
                params={**params, "select": "id", "limit": "1"},
            )
        if resp.status_code in (200, 206):
            ct = resp.headers.get("content-range", "")
            # content-range: 0-0/42  →  42
            if "/" in ct:
                try:
                    return int(ct.split("/")[1])
                except ValueError:
                    pass
            return len(resp.json())
    except Exception as exc:
        logger.debug("[milestones] _count %s error: %r", table, exc)
    return 0


async def _oldest_memory_date(user_id: str, companion_id: str) -> datetime | None:
    """Return the created_at of the oldest memory for this user+companion, or None."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            resp = await http.get(
                f"{_sb_url()}/rest/v1/memories",
                headers=_sb_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "companion_id": f"eq.{companion_id}",
                    "order": "created_at.asc",
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
        logger.debug("[milestones] _oldest_memory_date error: %r", exc)
    return None


async def _connection_score(user_id: str, companion_id: str) -> int:
    """Return the current connection_score from relationship_stats (default 50)."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            resp = await http.get(
                f"{_sb_url()}/rest/v1/relationship_stats",
                headers=_sb_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "companion_id": f"eq.{companion_id}",
                    "select": "connection_score",
                    "limit": "1",
                },
            )
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return int(rows[0].get("connection_score") or 50)
    except Exception as exc:
        logger.debug("[milestones] _connection_score error: %r", exc)
    return 50


# ── Milestone evaluation ───────────────────────────────────────────────────────

async def _gather_counts(user_id: str, companion_id: str) -> dict[str, Any]:
    """
    Query all data sources in parallel.  Each sub-call returns 0 on failure.
    Returns a dict of raw counts used by _evaluate_milestones.
    """
    import asyncio

    memories_task = _count("memories", {"user_id": f"eq.{user_id}", "companion_id": f"eq.{companion_id}"})
    goals_task = _count("goals", {"user_id": f"eq.{user_id}"})
    rituals_task = _count(
        "relationship_sessions",
        {"user_id": f"eq.{user_id}", "companion_id": f"eq.{companion_id}", "session_type": "eq.ritual"},
    )
    chapters_task = _count("legacy_chapters", {"user_id": f"eq.{user_id}"})
    oldest_task = _oldest_memory_date(user_id, companion_id)
    score_task = _connection_score(user_id, companion_id)

    memories_count, goals_count, ritual_count, chapters_count, oldest_dt, score = (
        await asyncio.gather(
            memories_task, goals_task, rituals_task, chapters_task, oldest_task, score_task,
            return_exceptions=True,
        )
    )

    # gather returns exceptions if a coroutine raises; coerce to safe defaults
    def _safe_int(v: Any, default: int) -> int:
        return v if isinstance(v, int) else default

    days_since_first = 0
    if isinstance(oldest_dt, datetime):
        delta = datetime.now(timezone.utc) - oldest_dt
        days_since_first = max(0, delta.days)

    return {
        "memories_count": _safe_int(memories_count, 0),
        "goals_count": _safe_int(goals_count, 0),
        "ritual_count": _safe_int(ritual_count, 0),
        "chapters_count": _safe_int(chapters_count, 0),
        "days_since_first": days_since_first,
        "connection_score": _safe_int(score, 50),
    }


def _is_unlocked(milestone_id: str, counts: dict[str, Any]) -> bool:
    """Stateless: returns True if the milestone condition is met given current counts."""
    mc = counts["memories_count"]
    gc = counts["goals_count"]
    rc = counts["ritual_count"]
    cc = counts["chapters_count"]
    ds = counts["days_since_first"]
    cs = counts["connection_score"]

    return {
        "first_memory":    mc >= 1,
        "memories_10":     mc >= 10,
        "memories_25":     mc >= 25,
        "memories_50":     mc >= 50,
        "first_goal":      gc >= 1,
        "goals_5":         gc >= 5,
        "goals_10":        gc >= 10,
        "first_reflection": rc >= 1,
        "reflections_4":   rc >= 4,
        "first_chapter":   cc >= 1,
        "one_week":        ds >= 7,
        "one_month":       ds >= 30,
        "bond_warm":       cs >= 25,
        "bond_close":      cs >= 65,
        "bond_closest":    cs >= 85,
    }.get(milestone_id, False)


def _progress(milestone: dict, counts: dict[str, Any]) -> tuple[int, int]:
    """Return (current_value, max_value) progress for display."""
    cat = milestone["category"]
    threshold = milestone["threshold"]
    if cat == "memory":
        return (min(counts["memories_count"], threshold), threshold)
    if cat == "goal":
        return (min(counts["goals_count"], threshold), threshold)
    if cat == "ritual":
        return (min(counts["ritual_count"], threshold), threshold)
    if cat == "chapter":
        return (min(counts["chapters_count"], threshold), threshold)
    if cat == "time":
        return (min(counts["days_since_first"], threshold), threshold)
    if cat == "bond":
        return (min(counts["connection_score"], threshold), threshold)
    return (0, threshold)


# ── Supabase read/write for user_milestones ───────────────────────────────────

async def _fetch_stored(user_id: str, companion_id: str) -> dict[str, dict]:
    """
    Return {milestone_id: row} for all rows in user_milestones for this user+companion.
    Returns {} on any error or if the table doesn't exist yet.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            resp = await http.get(
                f"{_sb_url()}/rest/v1/user_milestones",
                headers=_sb_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "companion_id": f"eq.{companion_id}",
                    "select": "milestone_id,unlocked_at,seen_at",
                },
            )
        if resp.status_code == 200:
            return {row["milestone_id"]: row for row in resp.json()}
    except Exception as exc:
        logger.debug("[milestones] _fetch_stored error: %r", exc)
    return {}


async def _record_unlock(user_id: str, companion_id: str, milestone_id: str) -> None:
    """Insert a row into user_milestones (on conflict do nothing)."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            await http.post(
                f"{_sb_url()}/rest/v1/user_milestones",
                headers={**_sb_headers(), "Prefer": "resolution=ignore-duplicates"},
                json={
                    "user_id": user_id,
                    "companion_id": companion_id,
                    "milestone_id": milestone_id,
                },
            )
    except Exception as exc:
        logger.debug("[milestones] _record_unlock error: %r", exc)


async def mark_milestones_seen(user_id: str, companion_id: str, milestone_ids: list[str]) -> None:
    """Set seen_at = now() for each given milestone_id."""
    if not milestone_ids:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    for mid in milestone_ids:
        try:
            async with httpx.AsyncClient(timeout=8.0) as http:
                await http.patch(
                    f"{_sb_url()}/rest/v1/user_milestones",
                    headers={**_sb_headers(), "Prefer": "return=minimal"},
                    params={
                        "user_id": f"eq.{user_id}",
                        "companion_id": f"eq.{companion_id}",
                        "milestone_id": f"eq.{mid}",
                    },
                    json={"seen_at": now_iso},
                )
        except Exception as exc:
            logger.debug("[milestones] mark_seen error for %s: %r", mid, exc)


# ── Main public API ────────────────────────────────────────────────────────────

async def get_milestones(user_id: str, companion_id: str) -> dict:
    """
    Evaluate all milestones for this user+companion.

    Returns:
      connection_score   int
      bond_level         str ("Warming" | "Warm" | "Close" | "Closest")
      milestones         list of milestone dicts (with locked/unlocked + progress)
      newly_unlocked     list of milestone_ids unlocked since last seen
    """
    import asyncio

    counts, stored = await asyncio.gather(
        _gather_counts(user_id, companion_id),
        _fetch_stored(user_id, companion_id),
        return_exceptions=False,
    )

    score = counts["connection_score"]
    if score >= 85:
        bond_level = "Closest"
    elif score >= 65:
        bond_level = "Close"
    elif score >= 25:
        bond_level = "Warm"
    else:
        bond_level = "Warming"

    newly_unlocked: list[str] = []
    milestones_out: list[dict] = []

    record_tasks = []

    for m in MILESTONE_DEFS:
        mid = m["id"]
        unlocked = _is_unlocked(mid, counts)
        stored_row = stored.get(mid)
        prog_current, prog_max = _progress(m, counts)

        entry: dict = {
            "id": mid,
            "title": m["title"],
            "description": m["description"],
            "icon": m["icon"],
            "category": m["category"],
            "unlocked": unlocked,
            "unlocked_at": stored_row["unlocked_at"] if stored_row else None,
            "seen": bool(stored_row and stored_row.get("seen_at")),
            "progress": prog_current,
            "progress_max": prog_max,
        }
        milestones_out.append(entry)

        if unlocked and not stored_row:
            # Newly unlocked — persist and flag for celebration
            newly_unlocked.append(mid)
            record_tasks.append(_record_unlock(user_id, companion_id, mid))
        elif unlocked and stored_row and not stored_row.get("seen_at"):
            # Previously unlocked but not yet seen by the frontend
            newly_unlocked.append(mid)

    if record_tasks:
        await asyncio.gather(*record_tasks, return_exceptions=True)

    return {
        "connection_score": score,
        "bond_level": bond_level,
        "milestones": milestones_out,
        "newly_unlocked": newly_unlocked,
    }
