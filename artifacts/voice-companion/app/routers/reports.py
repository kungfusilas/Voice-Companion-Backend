"""
Weekly Insight Report — Premium only.

Supabase table required (run once in Supabase SQL editor):

    create table if not exists weekly_reports (
      id            uuid primary key default gen_random_uuid(),
      user_id       uuid not null,
      companion_id  text not null,
      week_start    date not null,
      emotional_themes  jsonb,
      top_topics        jsonb,
      mood_arc          text,
      pattern           text,
      closing_note      text,
      created_at    timestamptz default now()
    );
    create index if not exists weekly_reports_user_week
      on weekly_reports (user_id, companion_id, week_start desc);
"""

import os
import json
import asyncio
import logging
import httpx
import anthropic
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException

from app.routers.auth import verify_token
from app import language as lang_module

logger = logging.getLogger(__name__)
router = APIRouter()

_HAIKU = "claude-haiku-4-5-20251001"
_TIER_RANK: dict[str, int] = {"free": 0, "basic": 1, "premium": 2, "power": 3, "elite": 4}


def _supa_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def _get_user_tier(user_id: str) -> str:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return "free"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers=_supa_headers(),
                params={"id": f"eq.{user_id}", "select": "subscription_tier", "limit": "1"},
            )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0].get("subscription_tier", "free") or "free"
    except Exception:
        pass
    return "free"


def _is_premium(tier: str) -> bool:
    return _TIER_RANK.get(tier, 0) >= _TIER_RANK["premium"]

def _is_power(tier: str) -> bool:
    return _TIER_RANK.get(tier, 0) >= _TIER_RANK["power"]


def _week_start_iso() -> str:
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


async def _fetch_memory_excerpts(user_id: str, companion_id: str) -> str:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return ""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/memories",
                headers=_supa_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "persona_id": f"eq.{companion_id}",
                    "created_at": f"gte.{week_ago}",
                    "select": "content,created_at",
                    "order": "created_at.asc",
                    "limit": "150",
                },
            )
        if resp.status_code == 200 and resp.json():
            return "\n".join(f"- {r['content']}" for r in resp.json())
    except Exception:
        pass
    return ""


async def _generate_report_data(user_id: str, companion_id: str) -> dict:
    excerpts, preferred_language = await asyncio.gather(
        _fetch_memory_excerpts(user_id, companion_id),
        lang_module.get_preferred_language(user_id),
    )

    if not excerpts:
        return {
            "emotional_themes": [],
            "top_topics": [],
            "mood_arc": None,
            "pattern": None,
            "closing_note": "No conversations were recorded this week. Come back and share what's on your mind — I'll be here.",
            "empty": True,
        }

    lang_name = lang_module.LANG_NAMES.get(preferred_language, preferred_language)
    lang_note = f"\nIMPORTANT: Write all text fields (emotional_themes, top_topics, mood_arc, pattern, closing_note) in {lang_name}." if preferred_language != "en" else ""

    prompt = f"""You are generating a private weekly insight report for a user from their AI companion app.

Below are memory excerpts from the past 7 days of conversations:
{excerpts}

Generate a JSON object with exactly these fields:
- emotional_themes: array of 3-5 short strings naming the dominant emotional states (e.g. "Anxiety around work", "Gratitude for family", "Restlessness")
- top_topics: array of 3-5 short strings for the most discussed themes (e.g. "Career uncertainty", "A difficult friendship", "Sleep habits")
- mood_arc: one sentence describing how the user's emotional state evolved through the week (e.g. "Started the week under pressure, found some relief midweek, ended with quiet resolve")
- pattern: one specific, concrete observation — something the companion genuinely noticed (e.g. "You mentioned your sister in 6 separate conversations this week", "Work came up every time you felt anxious")
- closing_note: 2-3 warm, personal sentences from the companion closing out the week — reference something specific from the excerpts

Return ONLY valid JSON. No markdown, no explanation.{lang_note}"""

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        message = client.messages.create(
            model=_HAIKU,
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        data = json.loads(message.content[0].text)
        data["empty"] = False
        return data
    except Exception as e:
        logger.warning("Report generation failed: %s", e)
        return {
            "emotional_themes": ["Reflection", "Connection"],
            "top_topics": ["Personal growth", "Daily life"],
            "mood_arc": "A week of meaningful conversations.",
            "pattern": None,
            "closing_note": "Thank you for sharing this week. Every conversation helps me understand you better.",
            "empty": False,
        }


async def _store_report(user_id: str, companion_id: str, report: dict) -> None:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return
    payload = {
        "user_id": user_id,
        "companion_id": companion_id,
        "week_start": _week_start_iso(),
        "emotional_themes": report.get("emotional_themes"),
        "top_topics": report.get("top_topics"),
        "mood_arc": report.get("mood_arc"),
        "pattern": report.get("pattern"),
        "closing_note": report.get("closing_note"),
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{url}/rest/v1/weekly_reports",
                headers=_supa_headers(),
                json=payload,
            )
    except Exception as e:
        logger.warning("Failed to store report: %s", e)


@router.get("")
async def get_weekly_report(companion_id: str = "aria", user_id: str = Depends(verify_token)):
    tier = await _get_user_tier(user_id)
    if not _is_power(tier):
        raise HTTPException(status_code=403, detail="Power tier required")

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return {"report": None}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/weekly_reports",
                headers=_supa_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "companion_id": f"eq.{companion_id}",
                    "order": "created_at.desc",
                    "limit": "1",
                },
            )
        if resp.status_code == 200 and resp.json():
            return {"report": resp.json()[0]}
    except Exception:
        pass
    return {"report": None}


@router.post("/generate")
async def generate_weekly_report(companion_id: str = "aria", user_id: str = Depends(verify_token)):
    tier = await _get_user_tier(user_id)
    if not _is_power(tier):
        raise HTTPException(status_code=403, detail="Power tier required")

    report = await _generate_report_data(user_id, companion_id)
    if not report.get("empty"):
        await _store_report(user_id, companion_id, report)
    return {"report": report}


async def run_weekly_reports_for_all_users() -> None:
    """Scheduled Monday job — generate reports for all premium users."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers=_supa_headers(),
                params={
                    "subscription_tier": "in.(power,elite)",
                    "select": "id,companion_id",
                    "limit": "500",
                },
            )
        if resp.status_code != 200:
            return
        for row in resp.json():
            try:
                uid = row["id"]
                cid = row.get("companion_id", "aria") or "aria"
                report = await _generate_report_data(uid, cid)
                if not report.get("empty"):
                    await _store_report(uid, cid, report)
            except Exception as e:
                logger.warning("Weekly report failed for user: %s", e)
    except Exception as e:
        logger.warning("Weekly report job failed: %s", e)
