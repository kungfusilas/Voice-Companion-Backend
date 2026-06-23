"""
Weekly Insight Report generator.

Retrieves the last 7 days of memories for a user+companion pair and uses
Claude Haiku to surface emotional themes, growth moments, recurring patterns,
and a suggested question for the next session.
"""
import os
import json
from datetime import datetime, timedelta, timezone

import httpx

from app import claude


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
