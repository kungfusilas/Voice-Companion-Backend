"""
Personality Drift Tracker.

Scores users on Big Five personality traits from recent messages using Claude Haiku,
persists snapshots to Supabase, and detects drift between the oldest and newest
of the last 4 snapshots.
"""
import logging
import os
import json
from datetime import datetime, timezone

import httpx

from app import claude

logger = logging.getLogger(__name__)

_SUPABASE_TABLE = "personality_scores"

_SCORE_SYSTEM = (
    "You are a psychologist analysing someone's messages to score their Big Five personality traits. "
    "Score each trait on a scale of 1-10 based on the evidence in the messages provided. "
    "Be precise — only use the text given, do not assume anything not present.\n\n"
    "Return ONLY valid JSON with exactly these keys (integer values 1-10):\n"
    '{"openness": 0, "conscientiousness": 0, "extraversion": 0, "agreeableness": 0, "neuroticism": 0}\n\n'
    "Return ONLY the JSON object — no markdown, no explanation."
)


async def score_personality(
    user_id: str,
    companion_id: str,
    recent_messages: list[str],
) -> dict:
    """
    Score the user on Big Five traits from their last N messages,
    persist the snapshot to Supabase, and return the score dict.
    Errors are logged and never bubble up — safe to fire-and-forget.
    """
    logger.debug(
        "[personality_tracker] score_personality: user=%s companion=%s msgs=%d",
        user_id[:8], companion_id, len(recent_messages),
    )
    try:
        joined = "\n".join(f"- {m}" for m in recent_messages)
        user_prompt = f"Here are the user's recent messages:\n\n{joined}\n\nScore their Big Five traits."

        raw = await claude.send_message(
            system_prompt=_SCORE_SYSTEM,
            history=[],
            user_message=user_prompt,
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

        scores = json.loads(cleaned)

        traits = ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]
        for t in traits:
            scores[t] = max(1, min(10, int(scores.get(t, 5))))

        scores["timestamp"] = datetime.now(timezone.utc).isoformat()

        await _save_snapshot(user_id, companion_id, scores)
        logger.info("[personality_tracker] snapshot saved: user=%s", user_id[:8])
        return scores

    except Exception as exc:
        logger.warning("[personality_tracker] score_personality ERROR: %r", exc)
        return {}


async def get_personality_drift(user_id: str, companion_id: str) -> dict:
    """
    Read the last 4 personality snapshots and compare oldest to newest.
    Returns which traits shifted by more than 1.5 points and in which direction.
    """
    logger.debug(
        "[personality_tracker] get_personality_drift: user=%s companion=%s",
        user_id[:8], companion_id,
    )
    try:
        snapshots = await _fetch_snapshots(user_id, companion_id, limit=4)

        if not snapshots:
            return {
                "snapshot_count": 0,
                "drift": [],
                "note": "No personality snapshots yet. Snapshots are taken every 10 messages.",
            }

        if len(snapshots) == 1:
            latest = snapshots[0].get("scores", {})
            return {
                "snapshot_count": 1,
                "drift": [],
                "latest_scores": latest,
                "note": "Only one snapshot so far — need at least 2 to detect drift.",
            }

        newest = snapshots[0].get("scores", {})
        oldest = snapshots[-1].get("scores", {})

        traits = ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]
        drift = []
        for trait in traits:
            new_val = newest.get(trait)
            old_val = oldest.get(trait)
            if new_val is None or old_val is None:
                continue
            delta = new_val - old_val
            if abs(delta) > 1.5:
                drift.append({
                    "trait": trait,
                    "direction": "up" if delta > 0 else "down",
                    "delta": round(delta, 2),
                    "from": old_val,
                    "to": new_val,
                })

        return {
            "snapshot_count": len(snapshots),
            "oldest_at": snapshots[-1].get("created_at"),
            "newest_at": snapshots[0].get("created_at"),
            "drift": drift,
            "latest_scores": newest,
        }

    except Exception as exc:
        logger.warning("[personality_tracker] get_personality_drift ERROR: %r", exc)
        return {"error": "Failed to retrieve drift data.", "drift": []}


async def _save_snapshot(user_id: str, companion_id: str, scores: dict) -> None:
    supabase_url = os.environ.get("SUPABASE_URL", "")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.post(
            f"{supabase_url}/rest/v1/{_SUPABASE_TABLE}",
            headers={
                "Authorization": f"Bearer {service_key}",
                "apikey": service_key,
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json={
                "user_id": user_id,
                "companion_id": companion_id,
                "scores": scores,
            },
        )
        if resp.status_code not in (200, 201):
            logger.warning(
                "[personality_tracker] _save_snapshot HTTP %d", resp.status_code
            )


async def _fetch_snapshots(user_id: str, companion_id: str, limit: int = 4) -> list[dict]:
    supabase_url = os.environ.get("SUPABASE_URL", "")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.get(
            f"{supabase_url}/rest/v1/{_SUPABASE_TABLE}",
            headers={
                "Authorization": f"Bearer {service_key}",
                "apikey": service_key,
            },
            params={
                "select": "scores,created_at",
                "user_id": f"eq.{user_id}",
                "companion_id": f"eq.{companion_id}",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )
        if resp.status_code == 200:
            return resp.json() or []
        logger.warning(
            "[personality_tracker] _fetch_snapshots HTTP %d", resp.status_code
        )
        return []
