"""
Weekly Insight Report generator.

Retrieves the last 7 days of memories for a user+companion pair and uses
Claude Haiku to surface emotional themes, growth moments, recurring patterns,
and a suggested question for the next session.

After the report is returned, a fire-and-forget coroutine runs the full
personality update pipeline:
  1. Score the user's Big Five traits from recent messages.
  2. Read the last 4 snapshots to compute drift.
  3. If any trait drifted past threshold, call personality_extractor.apply_drift_revision
     to revise the personality_map accordingly.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import httpx

from app import claude
from app import personality_tracker
from app import personality_extractor


async def _fetch_week_memories(user_id: str, companion_id: str) -> list[dict]:
    """
    Pull memories created in the last 7 days for this user+companion from Supabase.
    Uses raw httpx (same pattern as save_memory) for full transparency.
    """
    supabase_url = os.environ.get("SUPABASE_URL", "")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")

    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.get(
            f"{supabase_url}/rest/v1/memories",
            headers={
                "Authorization": f"Bearer {service_key}",
                "apikey": service_key,
            },
            params={
                "select": "content,memory_type,importance,emotional_theme,topic,created_at",
                "user_id": f"eq.{user_id}",
                "companion_id": f"eq.{companion_id}",
                "created_at": f"gte.{since}",
                "order": "created_at.desc",
                "limit": "100",
            },
        )
        if resp.status_code == 200:
            return resp.json() or []
        print(f"[weekly_insight] fetch_week_memories HTTP {resp.status_code}: {resp.text[:200]}")
        return []


_REPORT_SYSTEM = (
    "You are a compassionate relationship analyst reviewing a week of memories "
    "a companion has formed about a user. Your job is to surface meaningful insights "
    "that help the companion deepen the bond next week.\n\n"
    "Return ONLY valid JSON with exactly these four keys:\n"
    '{"emotional_themes": ["theme1", "theme2", "theme3"], '
    '"growth_moment": "one specific moment or shift showing progress or self-awareness", '
    '"recurring_pattern": "one pattern or habit worth gently exploring further", '
    '"next_session_question": "one thoughtful open-ended question the companion should ask next time"}\n\n'
    "If there are fewer than 3 distinct emotional themes, return what you can (pad with null).\n"
    "Return ONLY the JSON object — no markdown, no explanation."
)


async def _fetch_recent_user_messages(user_id: str, companion_id: str, limit: int = 10) -> list[str]:
    """
    Pull the most recent user-role messages from the conversations archive
    for this user+companion pair — used to feed the Big Five personality scorer.
    """
    supabase_url = os.environ.get("SUPABASE_URL", "")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not supabase_url or not service_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(
                f"{supabase_url}/rest/v1/conversations",
                headers={"Authorization": f"Bearer {service_key}", "apikey": service_key},
                params={
                    "select": "messages",
                    "user_id": f"eq.{user_id}",
                    "companion_id": f"eq.{companion_id}",
                    "order": "created_at.desc",
                    "limit": "5",
                },
            )
        if resp.status_code != 200:
            return []
        rows = resp.json() or []
        msgs: list[str] = []
        for row in rows:
            for m in row.get("messages") or []:
                if m.get("role") == "user" and m.get("content"):
                    msgs.append(m["content"])
                if len(msgs) >= limit:
                    break
            if len(msgs) >= limit:
                break
        return msgs[:limit]
    except Exception:
        return []


async def _weekly_personality_update(
    user_id: str,
    companion_id: str,
    recent_msgs: list[str],
) -> None:
    """
    Fire-and-forget coroutine that runs the full personality update pipeline:

    1. Score Big Five from recent messages and persist the snapshot.
    2. Fetch the last 4 snapshots and compute drift.
    3. If any trait drifted past the significance threshold, call
       personality_extractor.apply_drift_revision to revise the personality_map.

    All errors are swallowed — this must never affect the weekly report response.
    """
    try:
        await personality_tracker.score_personality(user_id, companion_id, recent_msgs)

        drift_result = await personality_tracker.get_personality_drift(user_id, companion_id)
        drifted_traits: list[dict] = drift_result.get("drift") or []

        if drifted_traits:
            print(
                f"[weekly_insight] drift detected for user={user_id} companion={companion_id}: "
                f"{[d['trait'] for d in drifted_traits]}"
            )
            await personality_extractor.apply_drift_revision(user_id, drifted_traits)
        else:
            print(
                f"[weekly_insight] no significant drift for user={user_id} companion={companion_id} "
                f"(snapshots={drift_result.get('snapshot_count', 0)})"
            )

    except Exception as exc:
        print(f"[weekly_insight] _weekly_personality_update ERROR: {exc!r}")


async def generate_weekly_report(user_id: str, companion_id: str) -> dict:
    """
    Generate a weekly insight report for the given user+companion pair.

    Returns a dict with keys:
      - emotional_themes: list[str]  (top 3)
      - growth_moment:    str
      - recurring_pattern: str
      - next_session_question: str
      - memory_count:     int  (how many memories were analysed)
      - period_days:      int  (always 7)
    """
    memories = await _fetch_week_memories(user_id, companion_id)
    print(f"[weekly_insight] generate_weekly_report: user={user_id} companion={companion_id} memories={len(memories)}")

    if not memories:
        return {
            "emotional_themes": [],
            "growth_moment": None,
            "recurring_pattern": None,
            "next_session_question": None,
            "memory_count": 0,
            "period_days": 7,
            "note": "No memories found for this period. Keep chatting to build up insights.",
        }

    memory_text = "\n".join(
        f"- [{m.get('memory_type', 'fact')}] {m.get('content', '').strip()}"
        for m in memories
        if m.get("content", "").strip()
    )

    user_prompt = (
        f"Here are the memories from the past 7 days ({len(memories)} total):\n\n"
        f"{memory_text}\n\n"
        "Generate the weekly insight report as JSON."
    )

    try:
        raw = await claude.send_message(
            system_prompt=_REPORT_SYSTEM,
            history=[],
            user_message=user_prompt,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        result = json.loads(cleaned)
        result["memory_count"] = len(memories)
        result["period_days"] = 7
        print(f"[weekly_insight] report generated OK for user={user_id}")

        # Fire-and-forget: full personality update pipeline (score → drift → revise map).
        # Fetch recent messages first (fast read); the heavy work happens in the background.
        recent_msgs = await _fetch_recent_user_messages(user_id, companion_id)
        if recent_msgs:
            asyncio.create_task(
                _weekly_personality_update(user_id, companion_id, recent_msgs)
            )

        return result

    except Exception as exc:
        print(f"[weekly_insight] generate_weekly_report ERROR: {exc!r}")
        return {
            "emotional_themes": [],
            "growth_moment": None,
            "recurring_pattern": None,
            "next_session_question": None,
            "memory_count": len(memories),
            "period_days": 7,
            "error": "Failed to generate report. Try again shortly.",
        }
