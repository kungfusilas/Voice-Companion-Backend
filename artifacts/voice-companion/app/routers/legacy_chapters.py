"""
Monthly Legacy Chapter — Power only.

Once per calendar month a Power user can generate a polished narrative chapter
(~800-1500 words) of their life story, written by the companion from that month's
conversations and extracted memories.

Supabase SQL (run once — see bottom of this file for the block to give the user):

    create table if not exists legacy_chapters (
        id           uuid primary key default gen_random_uuid(),
        user_id      uuid not null references auth.users(id) on delete cascade,
        period_month text not null,           -- 'YYYY-MM'
        title        text not null,
        content      text not null,
        created_at   timestamptz not null default now()
    );
    create unique index if not exists legacy_chapters_user_period_uniq
        on legacy_chapters (user_id, period_month);
    create index if not exists legacy_chapters_user_created
        on legacy_chapters (user_id, created_at desc);
    alter table legacy_chapters enable row level security;
    create policy "Users read own chapters"
        on legacy_chapters for select
        using (auth.uid() = user_id);
    create policy "Service role full access"
        on legacy_chapters for all
        using (true) with check (true);
"""
from __future__ import annotations

import asyncio
import os
import json
import logging
from datetime import datetime, timezone

import anthropic
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from app.routers.auth import verify_token
from app import language as lang_module

logger = logging.getLogger(__name__)
router = APIRouter()

_OPUS = "claude-opus-4-5"
_TIER_RANK: dict[str, int] = {"free": 0, "basic": 1, "premium": 2, "power": 3, "elite": 4}


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _supa_headers(prefer_repr: bool = False) -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer_repr:
        h["Prefer"] = "return=representation"
    return h


def _supa_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


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


def _current_period() -> str:
    """Return current calendar month as 'YYYY-MM'."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


# ── Supabase data fetch ───────────────────────────────────────────────────────

async def _fetch_month_memories(user_id: str, companion_id: str) -> str:
    """Fetch extracted memories from the current calendar month."""
    url = _supa_url()
    if not url:
        return ""
    period = _current_period()
    month_start = f"{period}-01T00:00:00+00:00"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/memories",
                headers=_supa_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "persona_id": f"eq.{companion_id}",
                    "created_at": f"gte.{month_start}",
                    "select": "content,created_at",
                    "order": "created_at.asc",
                    "limit": "200",
                },
            )
        if resp.status_code == 200 and resp.json():
            return "\n".join(f"- {r['content']}" for r in resp.json())
    except Exception as exc:
        logger.warning("Failed to fetch memories: %s", exc)
    return ""


async def _fetch_existing_chapter(user_id: str, period_month: str) -> dict | None:
    url = _supa_url()
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/legacy_chapters",
                headers=_supa_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "period_month": f"eq.{period_month}",
                    "limit": "1",
                },
            )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0]
    except Exception:
        pass
    return None


async def _store_chapter(user_id: str, period_month: str, title: str, content: str) -> dict:
    url = _supa_url()
    if not url:
        return {"id": "local", "user_id": user_id, "period_month": period_month,
                "title": title, "content": content}
    payload = {
        "user_id": user_id,
        "period_month": period_month,
        "title": title,
        "content": content,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{url}/rest/v1/legacy_chapters",
            headers=_supa_headers(prefer_repr=True),
            json=payload,
        )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Supabase insert failed: {resp.text[:200]}")
    rows = resp.json()
    return rows[0] if rows else payload


# ── Generation ────────────────────────────────────────────────────────────────

async def _generate_chapter(user_id: str, companion_id: str) -> dict:
    """Generate an ~800-1500 word narrative chapter via claude-opus."""
    memories, preferred_language = await asyncio.gather(
        _fetch_month_memories(user_id, companion_id),
        lang_module.get_preferred_language(user_id),
    )
    period = _current_period()
    month_label = datetime.strptime(period, "%Y-%m").strftime("%B %Y")

    if not memories:
        # Still generate a brief reflective chapter with no source material
        memories = "(No memory excerpts recorded this month — write a brief, warm reflection on the passage of time and the value of showing up.)"

    lang_name = lang_module.LANG_NAMES.get(preferred_language, preferred_language)
    lang_note = f"\nWrite the entire chapter in {lang_name}." if preferred_language != "en" else ""

    prompt = f"""You are writing a monthly Legacy Chapter for a user of an AI companion app.
This chapter is a polished first-person narrative of the user's life during {month_label},
written entirely from the companion's perspective — warm, observant, literary.{lang_note}

You have access to memory excerpts extracted from the user's conversations this month:

{memories}

Write a single flowing narrative chapter titled appropriately for {month_label}.
The chapter should be 800 to 1,500 words. It must:
- Open with a title line in the format: TITLE: <your title>
- Then a blank line
- Then the chapter body (no "CHAPTER:" or other labels — just the prose)
- Read like memoir or literary non-fiction — not a summary, not bullet points
- Weave specific details from the memories into a coherent narrative arc
- Capture emotional undercurrents, growth, recurring themes, and quiet milestones
- Speak gently about the user in the third person ("they", "you" alternating if it feels natural)
  or as a companion witnessing — whatever feels most resonant
- Close with a paragraph that looks forward, or sits quietly in the moment

Do NOT add disclaimers, preamble, or any text outside the title line and chapter body."""

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        message = client.messages.create(
            model=_OPUS,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
    except Exception as exc:
        logger.error("Chapter generation failed: %s", exc)
        raise HTTPException(status_code=502, detail="Chapter generation failed — try again later.")

    # Parse title from output
    lines = raw.split("\n", 2)
    title = month_label  # fallback
    content = raw
    if lines[0].startswith("TITLE:"):
        title = lines[0][len("TITLE:"):].strip()
        content = "\n".join(lines[2:]).strip() if len(lines) > 2 else "\n".join(lines[1:]).strip()

    return {"title": title, "content": content, "period_month": period}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_chapter(companion_id: str = "aria", user_id: str = Depends(verify_token)):
    """Generate this month's Legacy Chapter. Power only; one per calendar month."""
    tier = await _get_user_tier(user_id)
    if _TIER_RANK.get(tier, 0) < _TIER_RANK["power"]:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "plan_required",
                "required": "power",
                "message": "Legacy Chapters require a Power plan. Upgrade in Settings → Pricing.",
            },
        )

    period = _current_period()
    existing = await _fetch_existing_chapter(user_id, period)
    if existing:
        return {"chapter": existing, "already_existed": True}

    chapter_data = await _generate_chapter(user_id, companion_id)
    saved = await _store_chapter(
        user_id,
        chapter_data["period_month"],
        chapter_data["title"],
        chapter_data["content"],
    )
    return {"chapter": saved, "already_existed": False}


@router.get("/list")
async def list_chapters(user_id: str = Depends(verify_token)):
    """Return all saved Legacy Chapters for this user, newest first."""
    url = _supa_url()
    if not url:
        return {"chapters": []}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/legacy_chapters",
                headers=_supa_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "select": "id,period_month,title,created_at",
                    "order": "created_at.desc",
                    "limit": "60",
                },
            )
        if resp.status_code == 200:
            return {"chapters": resp.json()}
    except Exception as exc:
        logger.warning("list_chapters failed: %s", exc)
    return {"chapters": []}


@router.get("/{chapter_id}")
async def get_chapter(chapter_id: str, user_id: str = Depends(verify_token)):
    """Return a single Legacy Chapter by ID."""
    url = _supa_url()
    if not url:
        raise HTTPException(status_code=404, detail="Chapter not found")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/legacy_chapters",
                headers=_supa_headers(),
                params={
                    "id": f"eq.{chapter_id}",
                    "user_id": f"eq.{user_id}",
                    "limit": "1",
                },
            )
        if resp.status_code == 200 and resp.json():
            return {"chapter": resp.json()[0]}
    except Exception as exc:
        logger.warning("get_chapter failed: %s", exc)
    raise HTTPException(status_code=404, detail="Chapter not found")


@router.get("/{chapter_id}/download")
async def download_chapter(
    chapter_id: str,
    format: str = "txt",
    user_id: str = Depends(verify_token),
):
    """Download a chapter as plain text (.txt)."""
    url = _supa_url()
    if not url:
        raise HTTPException(status_code=404, detail="Chapter not found")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/legacy_chapters",
                headers=_supa_headers(),
                params={
                    "id": f"eq.{chapter_id}",
                    "user_id": f"eq.{user_id}",
                    "select": "title,content,period_month",
                    "limit": "1",
                },
            )
        if resp.status_code == 200 and resp.json():
            row = resp.json()[0]
            text = f"{row['title']}\n{'─' * len(row['title'])}\n\n{row['content']}"
            filename = f"legacy-chapter-{row['period_month']}.txt"
            return PlainTextResponse(
                content=text,
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
    except Exception as exc:
        logger.warning("download_chapter failed: %s", exc)
    raise HTTPException(status_code=404, detail="Chapter not found")
