"""
Extraction Protocol — Power tier only.

Returns a single versioned JSON bundle containing everything the app knows
about the authenticated user: personality profile, all memories across all
companions, all legacy chapters (full content), bond relationship history,
and the static companion persona configs.

Intended as the portable "companion data" format that can follow the user to
future devices or platforms.

GET /api/export  →  application/json  +  Content-Disposition: attachment
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.routers.auth import verify_token
from app import personality_extractor, personality_tracker
from app.companions import COMPANIONS

logger = logging.getLogger(__name__)
router = APIRouter()

_EXPORT_VERSION = "1.0"
_TIER_RANK: dict[str, int] = {"free": 0, "basic": 1, "premium": 2, "power": 3, "elite": 4}


# ── Supabase helpers (same pattern as legacy_chapters.py) ─────────────────────

def _supa_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _supa_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def _get_user_tier(user_id: str) -> str:
    url = _supa_url()
    if not url:
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


# ── Data fetchers ─────────────────────────────────────────────────────────────

async def _fetch_all_memories(user_id: str) -> list[dict]:
    """All memories across all companions, ordered oldest first."""
    url = _supa_url()
    if not url:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/memories",
                headers=_supa_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "select": "id,content,companion_id,memory_type,importance,created_at",
                    "order": "created_at.asc",
                    "limit": "2000",
                },
            )
        if resp.status_code == 200:
            return resp.json() or []
    except Exception as exc:
        logger.warning("export: failed to fetch memories: %s", exc)
    return []


async def _fetch_all_chapters(user_id: str) -> list[dict]:
    """All legacy chapters with full content, ordered oldest first."""
    url = _supa_url()
    if not url:
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/legacy_chapters",
                headers=_supa_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "select": "id,period_month,title,content,created_at",
                    "order": "created_at.asc",
                    "limit": "120",
                },
            )
        if resp.status_code == 200:
            return resp.json() or []
    except Exception as exc:
        logger.warning("export: failed to fetch legacy chapters: %s", exc)
    return []


async def _fetch_bond_history(user_id: str) -> dict:
    """Full bond score history across all companions, ordered oldest first."""
    url = _supa_url()
    if not url:
        return {"latest": None, "history": [], "trend": None}
    skills = [
        "listening", "empathy", "curiosity", "emotional_regulation",
        "conflict_resolution", "follow_through", "humor", "confidence",
    ]
    fields = ",".join(["id", "persona_id", "bond_score", "created_at"] + skills)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/bond_scores",
                headers=_supa_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "select": fields,
                    "order": "created_at.asc",
                    "limit": "500",
                },
            )
        if resp.status_code == 200:
            rows = resp.json() or []
            latest = rows[-1] if rows else None
            previous = rows[-2] if len(rows) >= 2 else None
            trend = (
                (latest["bond_score"] - previous["bond_score"])
                if latest and previous
                else None
            )
            return {"latest": latest, "history": rows, "trend": trend}
    except Exception as exc:
        logger.warning("export: failed to fetch bond scores: %s", exc)
    return {"latest": None, "history": [], "trend": None}


async def _fetch_personality_profile(user_id: str) -> dict:
    """
    Personality map (from profiles.personality_map) plus the latest Big Five
    snapshot and drift report for each companion, all gathered concurrently.
    """
    personality_map, *drift_results = await asyncio.gather(
        personality_extractor._fetch_current_map(user_id),
        *[
            personality_tracker.get_personality_drift(user_id, c.id)
            for c in COMPANIONS
        ],
        return_exceptions=True,
    )

    big_five_per_companion: dict = {}
    for companion, result in zip(COMPANIONS, drift_results):
        if isinstance(result, Exception):
            big_five_per_companion[companion.id] = {"error": "unavailable"}
        else:
            big_five_per_companion[companion.id] = result

    return {
        "personality_map": personality_map if isinstance(personality_map, dict) else {},
        "big_five_per_companion": big_five_per_companion,
    }


def _serialize_companions() -> list[dict]:
    """Static companion configs — no internal fields (voice_id, system_prompt)."""
    return [
        {
            "id": c.id,
            "name": c.name,
            "relationship_type": c.relationship_type,
            "personality_traits": c.personality_traits,
            "backstory": c.backstory,
            "nsfw_mode": c.nsfw_mode,
        }
        for c in COMPANIONS
    ]


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("")
async def export_user_data(user_id: str = Depends(verify_token)):
    """
    Extraction Protocol — Power tier only.

    All four data fetches (memories, chapters, bond scores, personality) run
    concurrently. The result is streamed back as a downloadable .json attachment.
    """
    tier = await _get_user_tier(user_id)
    if _TIER_RANK.get(tier, 0) < _TIER_RANK["power"]:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "plan_required",
                "required": "power",
                "message": (
                    "The Extraction Protocol requires a Power plan. "
                    "Upgrade in Settings → Pricing."
                ),
            },
        )

    memories, chapters, bond_relationship, personality_profile = await asyncio.gather(
        _fetch_all_memories(user_id),
        _fetch_all_chapters(user_id),
        _fetch_bond_history(user_id),
        _fetch_personality_profile(user_id),
    )

    bundle = {
        "export_version": _EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "personality_profile": personality_profile,
        "memories": memories,
        "legacy_chapters": chapters,
        "bond_relationship": bond_relationship,
        "companion_personas": _serialize_companions(),
    }

    payload = json.dumps(bundle, ensure_ascii=False, indent=2)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    uid_prefix = user_id[:8] if len(user_id) >= 8 else user_id
    filename = f"legacybond-export-{uid_prefix}-{date_str}.json"

    return StreamingResponse(
        iter([payload]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
