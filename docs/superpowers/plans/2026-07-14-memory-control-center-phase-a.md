# Memory Control Center — Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give all signed-in users a Memory Control Center to view/edit/delete what the companion remembers, disable sensitive categories, pause collection, and export — by extending the existing `memory_dashboard`.

**Architecture:** Add a per-user privacy layer. Each fact gets a `sensitivity` tag (classified for free, piggybacking existing extraction LLM calls). A pure `should_collect()` gate consults per-user `profiles.memory_settings` and is called before any fact is saved. The existing dashboard endpoints are widened to all signed-in users and extended with settings/purge/export.

**Tech Stack:** FastAPI, httpx→Supabase PostgREST, React+TS (Vite). Claude Haiku for classification.

## Global Constraints (verbatim from spec)

- Sensitivity tag set (exact strings): `health, mental-health, location, financial, sexual, family, religion-beliefs, political-views, none`.
- Core control endpoints use `verify_token` (all signed-in users), never `require_premium`.
- All DB access scoped to the JWT `user_id`; never trust a client-supplied user_id.
- The core-facts table is **`user_core_facts`** (NOT `core_facts`).
- Collection gate **fails open** (collect + log) on a settings-read error.
- Toggling a class OFF stops *future* collection only; deleting existing data is a separate, explicit **purge**.
- No new per-memory LLM cost: sensitivity classification piggybacks calls that already happen.

## Testing reality (read before Task 1)

This repo has **no test framework** (no `tests/`, no pytest, all logic is httpx→Supabase I/O). This plan therefore:
- Adds **pytest** for the one genuinely pure-logic unit — `should_collect()` — in a new `tests/` dir.
- Verifies I/O endpoints with `python -m py_compile` + **curl against the running app** (the pattern used throughout this project), documented per task. Endpoints are scoped by `user_id`, so curl checks use a real JWT the operator supplies as `$JWT`.

## File Structure

- Create `app/memory_settings.py` — per-user settings I/O + pure `should_collect()`. One responsibility: the privacy policy.
- Create `app/routers/memory_center.py` — the widened Control Center router (settings, purge, export, and the store-aware CRUD). Reuses helpers from `memory_dashboard.py`.
- Modify `app/memory_extractor.py` — classify sensitivity + apply the gate in both extractors.
- Modify `app/memory.py` — `should_remember` returns `sensitivity`; `save_memory` accepts + stores it.
- Modify `app/main.py` — mount `memory_center` router.
- Modify `src/pages/MemoryDashboard.tsx` — add Privacy (toggles + pause) and Export sections; show sensitivity.
- Create `tests/test_memory_settings.py` — pytest for `should_collect()`.
- Migration SQL is applied by the operator in Supabase (Task 1, Step 1).

---

### Task 1: Settings module + pure gate (`should_collect`)

**Files:**
- Migration: run SQL in Supabase (Step 1)
- Create: `app/memory_settings.py`
- Test: `tests/test_memory_settings.py`
- Modify: `requirements.txt` (add `pytest`)

**Interfaces:**
- Produces:
  - `SENSITIVITY_TAGS: frozenset[str]` — the 9 tags.
  - `should_collect(settings: dict, sensitivity: str, now: datetime | None = None) -> bool` — pure.
  - `async get_settings(user_id: str) -> dict` — reads `profiles.memory_settings`; `{}` on error.
  - `async update_settings(user_id: str, **fields) -> dict` — merges + persists; returns new settings.

- [ ] **Step 1: Apply the migration in Supabase (operator action)**

Run in the Supabase SQL editor:
```sql
ALTER TABLE memories        ADD COLUMN IF NOT EXISTS sensitivity text NOT NULL DEFAULT 'none';
ALTER TABLE user_core_facts ADD COLUMN IF NOT EXISTS sensitivity text NOT NULL DEFAULT 'none';
ALTER TABLE profiles        ADD COLUMN IF NOT EXISTS memory_settings jsonb NOT NULL DEFAULT '{}'::jsonb;
```

- [ ] **Step 2: Write the failing test**

`tests/test_memory_settings.py`:
```python
from datetime import datetime, timedelta, timezone
from app.memory_settings import should_collect

def test_collects_when_no_settings():
    assert should_collect({}, "financial") is True

def test_blocks_disabled_sensitivity():
    s = {"disabled_sensitivities": ["financial", "sexual"]}
    assert should_collect(s, "financial") is False
    assert should_collect(s, "health") is True

def test_paused_blocks_everything():
    s = {"collection_paused": True}
    assert should_collect(s, "none") is False

def test_pause_expires():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    s = {"collection_paused": True, "paused_until": past}
    assert should_collect(s, "none") is True  # window elapsed → collect

def test_pause_still_active():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    s = {"collection_paused": True, "paused_until": future}
    assert should_collect(s, "none") is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd artifacts/voice-companion && python -m pytest tests/test_memory_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: app.memory_settings`.

- [ ] **Step 4: Implement `app/memory_settings.py`**

```python
"""Per-user memory privacy settings + the pure collection gate."""
from __future__ import annotations
import logging, os
from datetime import datetime, timezone
import httpx

logger = logging.getLogger(__name__)

SENSITIVITY_TAGS = frozenset({
    "health", "mental-health", "location", "financial", "sexual",
    "family", "religion-beliefs", "political-views", "none",
})

def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")

def _sb_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

def should_collect(settings: dict, sensitivity: str, now: datetime | None = None) -> bool:
    """Pure decision: may we save a fact with this sensitivity for this user?"""
    now = now or datetime.now(timezone.utc)
    if settings.get("collection_paused"):
        pu = settings.get("paused_until")
        if not pu:
            return False  # paused indefinitely
        try:
            if now < datetime.fromisoformat(str(pu).replace("Z", "+00:00")):
                return False  # still within the pause window
        except (ValueError, TypeError):
            return False  # unparseable → treat as paused (safer)
    if sensitivity in set(settings.get("disabled_sensitivities") or []):
        return False
    return True

async def get_settings(user_id: str) -> dict:
    """Read profiles.memory_settings. Returns {} on any error (caller fails open)."""
    if not _sb_url():
        return {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{_sb_url()}/rest/v1/profiles", headers=_sb_headers(),
                            params={"id": f"eq.{user_id}", "select": "memory_settings", "limit": "1"})
        if r.status_code == 200 and r.json():
            return r.json()[0].get("memory_settings") or {}
    except Exception as exc:
        logger.warning("get_settings failed user=%.8s: %s", user_id, exc)
    return {}

async def update_settings(user_id: str, **fields) -> dict:
    """Merge fields into memory_settings and persist. Returns the merged settings."""
    current = await get_settings(user_id)
    current.update({k: v for k, v in fields.items() if v is not None})
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.patch(f"{_sb_url()}/rest/v1/profiles",
                          headers={**_sb_headers(), "Prefer": "return=minimal"},
                          params={"id": f"eq.{user_id}"},
                          json={"memory_settings": current})
    if r.status_code >= 400:
        raise RuntimeError(f"settings update failed (status {r.status_code})")
    return current
```
Also add `pytest` to `requirements.txt`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd artifacts/voice-companion && python -m pytest tests/test_memory_settings.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add artifacts/voice-companion/app/memory_settings.py artifacts/voice-companion/tests/test_memory_settings.py artifacts/voice-companion/requirements.txt
git commit -m "feat(memory): per-user settings module + pure should_collect gate"
```

---

### Task 2: Sensitivity classification + gate in core-facts extractor

**Files:**
- Modify: `app/memory_extractor.py` (`_CORE_FACTS_SYSTEM` ~168-178, `_CORE_FACTS_VALID_CATEGORIES` ~180, `extract_and_save_core_facts` ~185-293)

**Interfaces:**
- Consumes: `memory_settings.get_settings`, `memory_settings.should_collect`, `memory_settings.SENSITIVITY_TAGS`.

- [ ] **Step 1: Extend the extraction prompt to also return sensitivity**

Replace the `_CORE_FACTS_SYSTEM` string body so the JSON objects have three keys and the prompt lists the sensitivity tags:
```python
_CORE_FACTS_SYSTEM = (
    "Extract permanent facts about the user from this conversation turn. "
    "Focus on: family members (names, ages, relationships), job/occupation, "
    "location/city, health conditions, important life events, goals, and personality traits.\n"
    "Return ONLY a JSON array of objects with 'category', 'fact', and 'sensitivity' keys.\n"
    "Valid categories: family, work, location, health, goals, personality, history.\n"
    "Valid sensitivity: health, mental-health, location, financial, sexual, family, "
    "religion-beliefs, political-views, none. Use 'none' if the fact is not sensitive.\n"
    "Include only specific, concrete facts — not opinions or inferences. "
    "If nothing new is revealed, return [].\n"
    'Example: [{"category": "family", "fact": "Daughter named Emma, age 8", "sensitivity": "family"}, '
    '{"category": "work", "fact": "Works as a nurse on night shifts", "sensitivity": "none"}]'
)
```

- [ ] **Step 2: Load settings once and gate each fact**

Immediately after the `facts = [...]` validation block (currently ~225) and before building `to_insert`, add settings load:
```python
from app import memory_settings
settings = await memory_settings.get_settings(user_id)
```
In the validation list-comprehension, also normalise sensitivity (default 'none' if missing/invalid):
```python
facts = [
    {**f, "sensitivity": (f.get("sensitivity") if f.get("sensitivity") in memory_settings.SENSITIVITY_TAGS else "none")}
    for f in facts
    if isinstance(f, dict)
    and isinstance(f.get("category"), str) and f["category"] in _CORE_FACTS_VALID_CATEGORIES
    and isinstance(f.get("fact"), str) and f["fact"].strip()
]
```
In the `for item in facts:` loop, skip gated facts and store the tag:
```python
sens = item.get("sensitivity", "none")
if not memory_settings.should_collect(settings, sens):
    continue
...
to_insert.append({
    "user_id": user_id, "category": cat, "fact": fact_text,
    "sensitivity": sens, "confidence": 1.0,
    "created_at": now, "updated_at": now,
})
```

- [ ] **Step 3: Verify it compiles**

Run: `cd artifacts/voice-companion && python -m py_compile app/memory_extractor.py && echo OK`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add artifacts/voice-companion/app/memory_extractor.py
git commit -m "feat(memory): classify + gate sensitivity in core-facts extraction"
```

---

### Task 3: Sensitivity classification + gate in memories extractor

**Files:**
- Modify: `app/memory.py` (`should_remember` prompt + return; `save_memory` signature + insert)
- Modify: `app/memory_extractor.py` (`extract_and_save` ~119-165 — gate before save)

**Interfaces:**
- Produces: `memory.save_memory(..., sensitivity: str = "none")` persists a `sensitivity` column on `memories`.

- [ ] **Step 1: Add sensitivity to `should_remember`**

In `app/memory.py`, in the `should_remember` classifier prompt (the JSON schema near line 38 that already lists `"topic"`), add a `sensitivity` field with the same 9-tag enumeration and instruction to use `none` when not sensitive. Ensure the returned dict includes `sensitivity` (default `"none"`).

- [ ] **Step 2: Add `sensitivity` param to `save_memory`**

In `app/memory.py`, add `sensitivity: str = "none"` to the `save_memory` signature and include `"sensitivity": sensitivity` in the row dict it POSTs to `/rest/v1/memories`.

- [ ] **Step 3: Gate + pass sensitivity in `extract_and_save`**

In `app/memory_extractor.py` `extract_and_save`, after `result = await memory.should_remember(...)` and content sanitization, gate before saving:
```python
from app import memory_settings
sens = (result.get("sensitivity") if result.get("sensitivity") in memory_settings.SENSITIVITY_TAGS else "none")
settings = await memory_settings.get_settings(user_id)
if not memory_settings.should_collect(settings, sens):
    logger.debug("[memory_extractor] gated by settings (sens=%s) user=%.8s", sens, user_id)
    return
```
Pass `sensitivity=sens` into the `memory.save_memory(...)` call.

- [ ] **Step 4: Verify it compiles**

Run: `cd artifacts/voice-companion && python -m py_compile app/memory.py app/memory_extractor.py && echo OK`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add artifacts/voice-companion/app/memory.py artifacts/voice-companion/app/memory_extractor.py
git commit -m "feat(memory): classify + gate sensitivity in memories extraction"
```

---

### Task 4: Control Center router — read + settings endpoints

**Files:**
- Create: `app/routers/memory_center.py`
- Modify: `app/main.py` (mount router)

**Interfaces:**
- Consumes: `memory_dashboard._sb_url/_sb_headers` (import), `memory_settings.get_settings/update_settings/SENSITIVITY_TAGS`, `auth_middleware.verify_token`.
- Produces routes: `GET /api/memory-center`, `PATCH /api/memory-center/settings`.

- [ ] **Step 1: Implement the router (read + settings)**

`app/routers/memory_center.py`:
```python
import os, httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.auth_middleware import verify_token
from app import memory_settings as ms

router = APIRouter()

def _sb(): return os.environ.get("SUPABASE_URL", "").rstrip("/")
def _h():
    k = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}

async def _fetch(table: str, user_id: str, select: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"{_sb()}/rest/v1/{table}", headers=_h(),
                        params={"user_id": f"eq.{user_id}", "select": select, "order": "created_at.desc"})
    return r.json() if r.status_code in (200, 206) else []

@router.get("")
async def get_center(user_id: str = Depends(verify_token)) -> dict:
    memories = await _fetch("memories", user_id, "id,content,category,sensitivity,created_at")
    facts    = await _fetch("user_core_facts", user_id, "id,category,fact,sensitivity,created_at")
    return {"memories": memories, "core_facts": facts, "settings": await ms.get_settings(user_id)}

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
```

- [ ] **Step 2: Mount in `app/main.py`**

Next to the other `app.include_router(...)` lines:
```python
from app.routers import memory_center as memory_center_router
app.include_router(memory_center_router.router, prefix="/api/memory-center", tags=["memory-center"])
```

- [ ] **Step 3: Verify compile + live**

Run: `python -m py_compile app/routers/memory_center.py app/main.py && echo OK`
Then against the running app (operator supplies `$JWT`):
`curl -s -H "Authorization: Bearer $JWT" https://legacybond.ai/companion/api/memory-center | head -c 200`
Expected: JSON with `memories`, `core_facts`, `settings` keys.

- [ ] **Step 4: Commit**

```bash
git add artifacts/voice-companion/app/routers/memory_center.py artifacts/voice-companion/app/main.py
git commit -m "feat(memory): Control Center read + settings endpoints (all signed-in users)"
```

---

### Task 5: Delete / edit (store-aware) + purge

**Files:**
- Modify: `app/routers/memory_center.py`

**Interfaces:**
- Consumes: existing `memory_dashboard.patch_memory`-style edit/re-embed logic (mirror `memory_dashboard.py:195-297`, scoping by `user_id`).
- Produces routes: `DELETE /api/memory-center/{id}?store=`, `PATCH /api/memory-center/{id}?store=`, `POST /api/memory-center/purge?sensitivity=`.

- [ ] **Step 1: Add store-aware delete + edit + purge**

Append to `memory_center.py`. `store` ∈ {`memories`,`user_core_facts`}; reject others with 400. Delete/edit filter `id=eq.{id}&user_id=eq.{user_id}` (double-scope, as `memory_dashboard.delete_memory` does at `memory_dashboard.py:280-289`). For `memories` edits, re-embed via `app.memory.embed` exactly as `memory_dashboard.patch_memory` does (`memory_dashboard.py:216-222`). Purge deletes rows where `user_id=eq.{user_id}&sensitivity=eq.{tag}` from **both** tables.
```python
_STORES = {"memories", "user_core_facts"}

@router.delete("/{item_id}")
async def delete_item(item_id: str, store: str, user_id: str = Depends(verify_token)) -> dict:
    if store not in _STORES:
        raise HTTPException(400, "invalid store")
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.delete(f"{_sb()}/rest/v1/{store}", headers=_h(),
                           params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"})
    if r.status_code not in (200, 204):
        raise HTTPException(500, "delete failed")
    return {"ok": True, "deleted_id": item_id}

@router.post("/purge")
async def purge(sensitivity: str, user_id: str = Depends(verify_token)) -> dict:
    if sensitivity not in ms.SENSITIVITY_TAGS or sensitivity == "none":
        raise HTTPException(400, "invalid sensitivity")
    deleted = 0
    async with httpx.AsyncClient(timeout=15.0) as c:
        for table in _STORES:
            r = await c.delete(f"{_sb()}/rest/v1/{table}",
                               headers={**_h(), "Prefer": "return=representation"},
                               params={"user_id": f"eq.{user_id}", "sensitivity": f"eq.{sensitivity}"})
            if r.status_code in (200, 206):
                deleted += len(r.json())
    return {"ok": True, "sensitivity": sensitivity, "deleted": deleted}
```
(Edit endpoint: mirror `memory_dashboard.patch_memory` re-embed logic for `store == "memories"`; for `user_core_facts` just PATCH the `fact` text.)

- [ ] **Step 2: Verify compile + live**

Run: `python -m py_compile app/routers/memory_center.py && echo OK`
Live (operator, use a throwaway memory id): confirm `DELETE …/memory-center/<id>?store=memories` returns `{"ok":true}` and the row is gone from `GET`.

- [ ] **Step 3: Commit**

```bash
git add artifacts/voice-companion/app/routers/memory_center.py
git commit -m "feat(memory): store-aware delete/edit + sensitivity purge"
```

---

### Task 6: Export endpoint

**Files:**
- Modify: `app/routers/memory_center.py`

**Interfaces:**
- Produces route: `GET /api/memory-center/export?format=md|json`.

- [ ] **Step 1: Implement export**

```python
from fastapi.responses import PlainTextResponse, JSONResponse

@router.get("/export")
async def export(format: str = "md", user_id: str = Depends(verify_token)):
    memories = await _fetch("memories", user_id, "content,category,sensitivity,created_at")
    facts    = await _fetch("user_core_facts", user_id, "fact,category,sensitivity,created_at")
    if format == "json":
        return JSONResponse({"memories": memories, "core_facts": facts})
    lines = ["# What your companion remembers", "", "## Core facts"]
    for f in facts:
        lines.append(f"- ({f.get('category','')}/{f.get('sensitivity','none')}) {f.get('fact','')}")
    lines += ["", "## Memories"]
    for m in memories:
        lines.append(f"- ({m.get('category','')}/{m.get('sensitivity','none')}) {m.get('content','')}")
    return PlainTextResponse("\n".join(lines), media_type="text/markdown",
                             headers={"Content-Disposition": "attachment; filename=my-memories.md"})
```

- [ ] **Step 2: Verify compile + live**

Run: `python -m py_compile app/routers/memory_center.py && echo OK`
Live: `curl -s -H "Authorization: Bearer $JWT" "https://legacybond.ai/companion/api/memory-center/export?format=md" | head`
Expected: Markdown beginning `# What your companion remembers`.

- [ ] **Step 3: Commit**

```bash
git add artifacts/voice-companion/app/routers/memory_center.py
git commit -m "feat(memory): readable memory export (md/json)"
```

---

### Task 7: Frontend — Control Center (extend `MemoryDashboard.tsx`)

**Files:**
- Modify: `src/pages/MemoryDashboard.tsx`
- Modify: wherever the dashboard is gated/opened (search for `MemoryDashboard` usage) to allow all signed-in users.

**Interfaces:**
- Consumes: `GET/PATCH/DELETE/POST /api/memory-center*` via the existing `apiFetch` helper (`@/lib/api`).

- [ ] **Step 1: Point data fetch at `/companion/api/memory-center`** and read `memories`, `core_facts`, `settings` from the response (replace the premium-gated `/api/memory-dashboard` calls).

- [ ] **Step 2: Add a "Privacy" section** — render 8 toggles (all `SENSITIVITY_TAGS` except `none`), initial state from `settings.disabled_sensitivities`; on change, `PATCH /companion/api/memory-center/settings`. Add a "Pause all memory collection" switch bound to `settings.collection_paused`. Each tag row has a "Delete existing" button → `POST /companion/api/memory-center/purge?sensitivity=<tag>` behind a confirm dialog.

- [ ] **Step 3: Add an "Export" button** → fetch `/companion/api/memory-center/export?format=md` and trigger a file download (Blob + anchor, mirroring the download pattern in `VaultPage.tsx:downloadSession`).

- [ ] **Step 4: Show each memory's `sensitivity`** tag in the existing memory list rows.

- [ ] **Step 5: Verify in the browser** — load the page as a free (non-premium) signed-in user: memories list, toggle a class off, confirm the toggle persists on reload; export downloads a readable file.

- [ ] **Step 6: Commit**

```bash
git add artifacts/voice-companion/src/pages/MemoryDashboard.tsx
git commit -m "feat(memory): Control Center UI — privacy toggles, pause, export, sensitivity"
```

---

### Task 8: Rebuild frontend, final verification, PR

- [ ] **Step 1:** Build the frontend so `dist/` reflects the changes (the deploy serves `dist/public`): run the project's frontend build (`pnpm --dir artifacts/voice-companion build` or the repo's documented build) and commit the `dist/` artifacts if the repo commits built assets (it does — see `dist/public/assets`).
- [ ] **Step 2:** `python -m py_compile` across all changed `app/` files → `OK`.
- [ ] **Step 3:** `python -m pytest tests/ -v` → all pass.
- [ ] **Step 4:** Confirm the migration (Task 1 Step 1) has been applied in Supabase.
- [ ] **Step 5:** Open a PR to `main`; operator reviews, merges, and Republishes; then smoke-test: load the Control Center as a free user, toggle a class, send a chat message that would produce a fact in that class, confirm it is NOT stored.

---

## Self-Review

**Spec coverage:** view (T4) · edit/delete (T5) · never-remember/delete specific (T5) · disable categories (T1 gate + T2/T3 enforcement + T4 settings + T7 UI) · pause (T1 gate + T4 + T7) · export (T6) · all-signed-in access (T4) · sensitivity classification piggyback (T2/T3) · fail-open (T1 `get_settings` returns `{}`; `should_collect({})` collects). Phase-B items (provenance, confidence, conflict resolution, conversational) intentionally absent. ✔ No gaps.

**Placeholder scan:** No TBD/TODO. The two "mirror existing X" references (edit re-embed, download pattern) cite exact file:line to copy — concrete, not placeholders.

**Type consistency:** `should_collect(settings, sensitivity, now=None)->bool`, `get_settings->dict`, `update_settings->dict`, `SENSITIVITY_TAGS` used identically across T1–T6. `sensitivity` column added on both `memories` and `user_core_facts`; both read in T4/T6 and written in T2/T3. Store names constrained to the same `{memories, user_core_facts}` set in T5. ✔
