"""
Memory Dashboard — premium-only CRUD + AI auto-categorization.

All endpoints are scoped strictly to the authenticated user_id from the Bearer
JWT.  Client-supplied user_id values are never trusted.

Endpoints:
  GET    /api/memory-dashboard?companion_id=       grouped by category
  PATCH  /api/memory-dashboard/{memory_id}         edit text / toggle locked / toggle sensitive
  DELETE /api/memory-dashboard/{memory_id}?companion_id=   delete (409 if locked)
  POST   /api/memory-dashboard/backfill?companion_id=      batch-categorize uncategorized rows

DDL required (user runs in Supabase):
  ALTER TABLE memories ADD COLUMN IF NOT EXISTS category  text    NOT NULL DEFAULT 'uncategorized';
  ALTER TABLE memories ADD COLUMN IF NOT EXISTS locked    boolean NOT NULL DEFAULT false;
  ALTER TABLE memories ADD COLUMN IF NOT EXISTS sensitive boolean NOT NULL DEFAULT false;
  CREATE INDEX IF NOT EXISTS memories_user_companion_category
      ON memories (user_id, companion_id, category);
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth_middleware import verify_token
from app.routers.tier_check import require_premium
from app import memory as mem_module

logger = logging.getLogger(__name__)
router = APIRouter()

CATEGORIES = [
    "people", "goals", "milestones", "preferences",
    "wounds", "wins", "dreams", "reminders", "uncategorized",
]

_CLASSIFY_PROMPT = (
    "Classify this memory into EXACTLY ONE of these categories:\n"
    "people, goals, milestones, preferences, wounds, wins, dreams, reminders\n\n"
    "Rules:\n"
    "- people: memories about specific people (family, friends, relationships)\n"
    "- goals: things the user wants to achieve or is working toward\n"
    "- milestones: past achievements, events, or turning points\n"
    "- preferences: likes, dislikes, tastes, habits\n"
    "- wounds: pain, regrets, fears, struggles\n"
    "- wins: successes, proud moments, breakthroughs\n"
    "- dreams: hopes, wishes, aspirations\n"
    "- reminders: things to follow up on, check-ins, practical notes\n\n"
    "Respond with ONLY the single category word in lowercase. "
    "If genuinely uncertain, respond: uncategorized\n\n"
    "Memory: {content}"
)


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


async def _fetch_memory(memory_id: str, user_id: str, companion_id: str) -> dict | None:
    """Fetch a single memory row scoped to user_id+companion_id. Returns None if not found."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            resp = await http.get(
                f"{_sb_url()}/rest/v1/memories",
                headers=_sb_headers(),
                params={
                    "id": f"eq.{memory_id}",
                    "user_id": f"eq.{user_id}",
                    "companion_id": f"eq.{companion_id}",
                    "select": "id,content,memory_type,importance,category,locked,sensitive,created_at",
                    "limit": "1",
                },
            )
        if resp.status_code == 200:
            rows = resp.json()
            return rows[0] if rows else None
    except Exception as exc:
        logger.warning("[memory_dashboard] _fetch_memory error: %r", exc)
    return None


async def _classify_content(content: str) -> str:
    """Call Claude Haiku to classify content into one of 9 categories.
    Returns 'uncategorized' on any error."""
    try:
        from app import claude  # late import to avoid circular
        prompt = _CLASSIFY_PROMPT.format(content=content[:500])
        raw = await claude.send_message(
            system_prompt="You are a memory classifier. Respond with only the category word.",
            history=[],
            user_message=prompt,
            model="claude-haiku-4-5-20251001",
            max_tokens=16,
        )
        cat = raw.strip().lower().rstrip(".")
        return cat if cat in CATEGORIES else "uncategorized"
    except Exception as exc:
        logger.warning("[memory_dashboard] _classify_content error: %r", exc)
        return "uncategorized"


async def _patch_category(memory_id: str, category: str) -> None:
    """PATCH the category column on a memory row. Silently ignores errors."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            await http.patch(
                f"{_sb_url()}/rest/v1/memories",
                headers={**_sb_headers(), "Prefer": "return=minimal"},
                params={"id": f"eq.{memory_id}"},
                json={"category": category},
            )
    except Exception as exc:
        logger.debug("[memory_dashboard] _patch_category error: %r", exc)


async def categorize_memory_async(memory_id: str, content: str) -> None:
    """Classify and persist category for a single memory. Designed for create_task()."""
    category = await _classify_content(content)
    await _patch_category(memory_id, category)
    logger.debug("[memory_dashboard] categorized memory %s → %s", memory_id, category)


# ── Endpoints ──────────────────────────────────────────────────────────────────

_LIST_SELECT = "id,content,memory_type,importance,category,locked,sensitive,created_at"


@router.get("")
async def list_memories_grouped(
    companion_id: str = Query(...),
    user_id: str = Depends(verify_token),
) -> dict:
    """Return all memories grouped by category. Includes locked and sensitive fields."""
    await require_premium(user_id)
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(
                f"{_sb_url()}/rest/v1/memories",
                headers=_sb_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "companion_id": f"eq.{companion_id}",
                    "order": "created_at.desc",
                    "select": _LIST_SELECT,
                },
            )
        if resp.status_code not in (200, 206):
            raise HTTPException(500, "Failed to fetch memories")
        rows: list[dict] = resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[memory_dashboard] list error: %r", exc)
        raise HTTPException(500, "Failed to fetch memories")

    # Normalise missing columns (before DDL is applied they won't be present)
    groups: dict[str, list] = {cat: [] for cat in CATEGORIES}
    for row in rows:
        cat = row.get("category") or "uncategorized"
        if cat not in groups:
            cat = "uncategorized"
        row["locked"] = bool(row.get("locked"))
        row["sensitive"] = bool(row.get("sensitive"))
        groups[cat].append(row)

    return {"companion_id": companion_id, "groups": groups, "total": len(rows)}


class PatchMemoryRequest(BaseModel):
    companion_id: str
    text: str | None = None          # new content (triggers re-embed)
    locked: bool | None = None       # toggle lock
    sensitive: bool | None = None    # toggle sensitive


@router.patch("/{memory_id}")
async def patch_memory(
    memory_id: str,
    body: PatchMemoryRequest,
    user_id: str = Depends(verify_token),
) -> dict:
    """Edit text (re-embeds), or toggle locked / sensitive flags."""
    await require_premium(user_id)

    # Verify ownership
    existing = await _fetch_memory(memory_id, user_id, body.companion_id)
    if not existing:
        raise HTTPException(404, "Memory not found")

    update: dict = {}

    if body.text is not None:
        new_text = body.text.strip()
        if not new_text:
            raise HTTPException(400, "Text cannot be empty")
        # Re-embed in the background (existing embed() helper)
        try:
            embedding = await mem_module.embed(new_text)
            vec_str = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
            update["content"] = new_text
            update["embedding"] = vec_str
            # Re-classify asynchronously
            asyncio.create_task(categorize_memory_async(memory_id, new_text))
        except Exception as exc:
            logger.warning("[memory_dashboard] re-embed failed: %r", exc)
            # Still update the text even if re-embedding fails
            update["content"] = new_text

    if body.locked is not None:
        update["locked"] = body.locked
    if body.sensitive is not None:
        update["sensitive"] = body.sensitive

    if not update:
        return {"ok": True, "memory": existing}

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.patch(
                f"{_sb_url()}/rest/v1/memories",
                headers={**_sb_headers(prefer_repr=True)},
                params={
                    "id": f"eq.{memory_id}",
                    "user_id": f"eq.{user_id}",  # double-scope for safety
                },
                json=update,
            )
        if resp.status_code not in (200, 204):
            raise HTTPException(500, "Failed to update memory")
        rows = resp.json() if resp.status_code == 200 else []
        return {"ok": True, "memory": rows[0] if rows else existing}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[memory_dashboard] patch error: %r", exc)
        raise HTTPException(500, "Failed to update memory")


@router.delete("/{memory_id}", status_code=200)
async def delete_memory(
    memory_id: str,
    companion_id: str = Query(...),
    user_id: str = Depends(verify_token),
) -> dict:
    """Delete a memory. Returns 409 if locked=true."""
    await require_premium(user_id)

    existing = await _fetch_memory(memory_id, user_id, companion_id)
    if not existing:
        raise HTTPException(404, "Memory not found")

    if existing.get("locked"):
        raise HTTPException(
            409,
            detail={
                "code": "memory_locked",
                "message": "This memory is locked. Unlock it before deleting.",
            },
        )

    try:
        async with httpx.AsyncClient(timeout=8.0) as http:
            resp = await http.delete(
                f"{_sb_url()}/rest/v1/memories",
                headers=_sb_headers(),
                params={
                    "id": f"eq.{memory_id}",
                    "user_id": f"eq.{user_id}",  # double-scope
                },
            )
        if resp.status_code not in (200, 204):
            raise HTTPException(500, "Failed to delete memory")
        return {"ok": True, "deleted_id": memory_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[memory_dashboard] delete error: %r", exc)
        raise HTTPException(500, "Failed to delete memory")


@router.post("/backfill", status_code=200)
async def backfill_categories(
    companion_id: str = Query(...),
    batch_size: int = Query(default=20, ge=1, le=50),
    user_id: str = Depends(verify_token),
) -> dict:
    """Classify up to batch_size uncategorized memories for this user+companion."""
    await require_premium(user_id)

    # Fetch uncategorized rows
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(
                f"{_sb_url()}/rest/v1/memories",
                headers=_sb_headers(),
                params={
                    "user_id": f"eq.{user_id}",
                    "companion_id": f"eq.{companion_id}",
                    "category": "eq.uncategorized",
                    "order": "created_at.asc",
                    "limit": str(batch_size),
                    "select": "id,content",
                },
            )
        if resp.status_code not in (200, 206):
            raise HTTPException(500, "Failed to fetch memories for backfill")
        rows: list[dict] = resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[memory_dashboard] backfill fetch error: %r", exc)
        raise HTTPException(500, "Failed to fetch memories for backfill")

    if not rows:
        return {"ok": True, "classified": 0, "remaining": 0}

    # Classify and patch concurrently
    tasks = [categorize_memory_async(r["id"], r["content"]) for r in rows]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    errors = sum(1 for r in results if isinstance(r, Exception))

    logger.info("[memory_dashboard] backfill: classified=%d errors=%d", len(rows) - errors, errors)
    return {
        "ok": True,
        "classified": len(rows) - errors,
        "errors": errors,
        "remaining": len(rows) == batch_size,  # True means there may be more
    }
