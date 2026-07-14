"""Memory Control Center — user-facing control over what the companion remembers.

Every endpoint uses `verify_token` and is scoped to the authenticated user_id.
Available to all signed-in users (privacy/control is not premium-gated).

Static routes (/settings, /export, /purge) are declared before the dynamic
/{item_id} routes so, e.g., PATCH /settings never falls into the edit handler.
"""
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from app.auth_middleware import verify_token
from app import memory_settings as ms

router = APIRouter()

_STORES = {"memories", "user_core_facts"}


def _sb() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _h() -> dict:
    k = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


async def _fetch(table: str, user_id: str, select: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(
            f"{_sb()}/rest/v1/{table}",
            headers=_h(),
            params={"user_id": f"eq.{user_id}", "select": select, "order": "created_at.desc"},
        )
    return r.json() if r.status_code in (200, 206) else []


# ── Read ──────────────────────────────────────────────────────────────────────

@router.get("")
async def get_center(user_id: str = Depends(verify_token)) -> dict:
    """All of the user's memories + core facts (with sensitivity) and their settings."""
    memories = await _fetch("memories", user_id, "id,content,category,sensitivity,created_at")
    facts = await _fetch("user_core_facts", user_id, "id,category,fact,sensitivity,created_at")
    return {"memories": memories, "core_facts": facts, "settings": await ms.get_settings(user_id)}


@router.get("/export")
async def export(fmt: str = Query("md", alias="format"), user_id: str = Depends(verify_token)):
    """Readable export of everything the companion remembers. Markdown by default."""
    memories = await _fetch("memories", user_id, "content,category,sensitivity,created_at")
    facts = await _fetch("user_core_facts", user_id, "fact,category,sensitivity,created_at")
    if fmt == "json":
        return JSONResponse({"memories": memories, "core_facts": facts})
    lines = ["# What your companion remembers", "", "## Core facts"]
    for f in facts:
        lines.append(f"- ({f.get('category', '')}/{f.get('sensitivity', 'none')}) {f.get('fact', '')}")
    lines += ["", "## Memories"]
    for m in memories:
        lines.append(f"- ({m.get('category', '')}/{m.get('sensitivity', 'none')}) {m.get('content', '')}")
    return PlainTextResponse(
        "\n".join(lines),
        media_type="text/markdown",
        headers={"Content-Disposition": "attachment; filename=my-memories.md"},
    )


# ── Settings ──────────────────────────────────────────────────────────────────

class SettingsBody(BaseModel):
    disabled_sensitivities: list[str] | None = None
    collection_paused: bool | None = None
    paused_until: str | None = None


@router.patch("/settings")
async def patch_settings(body: SettingsBody, user_id: str = Depends(verify_token)) -> dict:
    if body.disabled_sensitivities is not None:
        bad = [t for t in body.disabled_sensitivities if t not in ms.SENSITIVITY_TAGS or t == "none"]
        if bad:
            raise HTTPException(400, f"invalid sensitivity tags: {bad}")
    return await ms.update_settings(
        user_id,
        disabled_sensitivities=body.disabled_sensitivities,
        collection_paused=body.collection_paused,
        paused_until=body.paused_until,
    )


# ── Purge a whole sensitivity class (explicit, confirmed) ─────────────────────

@router.post("/purge")
async def purge(sensitivity: str = Query(...), user_id: str = Depends(verify_token)) -> dict:
    """Delete all existing facts of one sensitivity class across BOTH stores."""
    if sensitivity not in ms.SENSITIVITY_TAGS or sensitivity == "none":
        raise HTTPException(400, "invalid sensitivity")
    deleted = 0
    async with httpx.AsyncClient(timeout=15.0) as c:
        for table in _STORES:
            r = await c.delete(
                f"{_sb()}/rest/v1/{table}",
                headers={**_h(), "Prefer": "return=representation"},
                params={"user_id": f"eq.{user_id}", "sensitivity": f"eq.{sensitivity}"},
            )
            if r.status_code in (200, 206):
                deleted += len(r.json())
    return {"ok": True, "sensitivity": sensitivity, "deleted": deleted}


# ── Store-aware delete / edit (dynamic routes — declared last) ─────────────────

@router.delete("/{item_id}")
async def delete_item(item_id: str, store: str = Query(...), user_id: str = Depends(verify_token)) -> dict:
    if store not in _STORES:
        raise HTTPException(400, "invalid store")
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.delete(
            f"{_sb()}/rest/v1/{store}",
            headers=_h(),
            params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
        )
    if r.status_code not in (200, 204):
        raise HTTPException(500, "delete failed")
    return {"ok": True, "deleted_id": item_id}


class EditBody(BaseModel):
    store: str
    text: str


@router.patch("/{item_id}")
async def edit_item(item_id: str, body: EditBody, user_id: str = Depends(verify_token)) -> dict:
    if body.store not in _STORES:
        raise HTTPException(400, "invalid store")
    new_text = body.text.strip()
    if not new_text:
        raise HTTPException(400, "text cannot be empty")
    if body.store == "memories":
        # Re-embed on content change (mirrors memory_dashboard.patch_memory)
        from app import memory as mem_module
        update: dict = {"content": new_text}
        try:
            embedding = await mem_module.embed(new_text)
            update["embedding"] = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
        except Exception:
            pass  # still update the text even if re-embed fails
    else:
        update = {"fact": new_text}
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.patch(
            f"{_sb()}/rest/v1/{body.store}",
            headers={**_h(), "Prefer": "return=minimal"},
            params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
            json=update,
        )
    if r.status_code not in (200, 204):
        raise HTTPException(500, "edit failed")
    return {"ok": True, "id": item_id}
