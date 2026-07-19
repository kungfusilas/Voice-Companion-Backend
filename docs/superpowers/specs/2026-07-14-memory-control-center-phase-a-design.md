# Memory Control Center — Phase A (Control & Privacy MVP)

Date: 2026-07-14
Status: Design approved; pending spec review → implementation plan
Scope: Phase A only. Phase B (Transparency) is a separate, later spec.

## 1. Purpose

Give users direct, visible control over what their companion remembers, and let them
stop the companion from collecting sensitive categories of information. This is a
trust/privacy differentiator for a product built on long-term personal memory.

The full idea spans several sub-features of very different depth, so it is phased:

- **Phase A (this spec):** the deterministic control surface — view / edit / delete
  memories, a per-user privacy layer (sensitivity tags + category toggles), pause
  collection, and export. Ships the reliable UI + APIs.
- **Phase B (later spec):** transparency — "why was this memory used in a response"
  (provenance), confidence disclosure ("I may remember this incorrectly"), and
  conflict resolution (`newest confirmed > newest inferred > older`).
- **Conversational control** ("delete what we talked about re: X") is a deliberate
  fast-follow that *reuses Phase A's APIs* with a mandatory confirmation step. It is
  intentionally NOT in Phase A because it depends on LLM intent detection (which
  misfires) and on the delete API existing first. A companion must never silently
  delete on misheard intent, and must never issue a false "okay, forgotten."

## 2. What already exists (baseline)

A premium-only Memory Dashboard already provides, on the `memories` table:

- `GET /api/memory-dashboard` — memories grouped by browse category
- `PATCH /api/memory-dashboard/{id}` — edit text (re-embeds), toggle `locked` / `sensitive`
- `DELETE /api/memory-dashboard/{id}` — delete (409 if `locked`)
- `POST /api/memory-dashboard/backfill` — AI auto-categorization
- Frontend: `MemoryDashboard.tsx`
- `memories` table already has `category`, `locked`, `sensitive`, `importance`.

Phase A **extends** this rather than building a parallel module.

## 3. Key decisions (locked during brainstorming)

1. **Sensitivity is a separate axis from browse category** (not one merged taxonomy).
   A memory keeps its browse category (`people/goals/wounds/…`) AND gets one
   **sensitivity tag**. Toggles and privacy controls act on the sensitivity tag.
2. **Sensitivity tag set (9):** `health`, `mental-health`, `location`, `financial`,
   `sexual`, `family`, `religion-beliefs`, `political-views`, `none`.
3. **Core control is available to all signed-in users** (not premium-gated). Sensitivity
   classification runs for everyone. Any premium flourish (e.g., AI auto-categorize
   backfill) may remain gated.
4. **Two suppression mechanisms, cleanly split:**
   - **Delete a fact** = one-off removal. No per-fact suppression list; a deleted fact
     *could* be re-learned if the user mentions it again (accepted trade-off).
   - **Category toggle OFF** = the durable, forward-looking "stop keeping this whole
     sensitivity class" control.
5. **Conversational control deferred** to a fast-follow that reuses these APIs with a
   confirmation step.

## 4. Architecture

Extend the existing `memory_dashboard` backend + `MemoryDashboard.tsx` into the
"Memory Control Center." Widen access (all signed-in users), add the privacy layer,
and enforce collection rules at the extraction entry points.

### 4.1 Data model (Supabase DDL — user runs once)

```sql
ALTER TABLE memories        ADD COLUMN IF NOT EXISTS sensitivity text NOT NULL DEFAULT 'none';
ALTER TABLE user_core_facts ADD COLUMN IF NOT EXISTS sensitivity text NOT NULL DEFAULT 'none';
ALTER TABLE profiles        ADD COLUMN IF NOT EXISTS memory_settings jsonb NOT NULL DEFAULT '{}'::jsonb;

-- NOTE: the core-facts table is `user_core_facts` (the design draft earlier said
-- `core_facts`). All references below use `user_core_facts`.
```

- `sensitivity` is one of the 9 tags. The existing `memories.sensitive boolean` becomes
  derived (`sensitivity != 'none'`); keep it in sync for backward compatibility.
- `profiles.memory_settings` shape:
  ```json
  { "disabled_sensitivities": ["financial", "sexual"],
    "collection_paused": false,
    "paused_until": null }
  ```

### 4.2 Stores governed in Phase A

- **View / edit / delete UI:** `memories` (extends today's dashboard). `core_facts`
  shown in a read-only-plus-delete section.
- **Collection rules (pause + toggles):** enforced at the two text-fact extractors —
  `memory_extractor.extract_and_save` (→ `memories`) and `extract_and_save_core_facts`
  (→ `core_facts`). Graphiti and future-memory get the same gate if trivial to add;
  otherwise noted as Phase A+ follow-up.

### 4.3 The collection gate

A single shared helper, called before any fact is saved:

```
should_collect(user_id, sensitivity) -> bool
  - load user's memory_settings (cached; changes rarely)
  - if collection_paused (and paused_until in the future / null) -> False
  - if sensitivity in disabled_sensitivities -> False
  - else True
```

- **Sensitivity classification piggybacks on the existing extraction LLM call.** The
  extractor already calls Claude to produce `{category, fact}`; we add `sensitivity`
  to that same prompt and output. **No new per-memory LLM cost.**
- **Fail-open on settings-read error** (collect + log): a transient blip must not
  silently kill all memory, and deletion is always available afterward.

## 5. API surface

All endpoints use `verify_token` and are strictly scoped to the authenticated `user_id`.
Mounted under `/api/memory-center` (the old `/api/memory-dashboard` paths may be aliased
during transition).

- `GET  /api/memory-center` — memories + core_facts grouped, each with its sensitivity
  tag; also returns the user's current `memory_settings`.
- `PATCH /api/memory-center/{id}?store=memories|core_facts` — edit a fact's text
  (memories are re-embedded; reuses existing dashboard logic). The `store` param selects
  the table, since memories and core_facts are distinct.
- `DELETE /api/memory-center/{id}?store=memories|core_facts` — delete one fact
  (409 if `locked`; `locked` applies to memories only).
- `PATCH /api/memory-center/settings` — set `disabled_sensitivities`,
  `collection_paused`, `paused_until`.
- `POST /api/memory-center/purge?sensitivity=<tag>` — explicit, confirmed bulk delete of
  existing facts in a class, across BOTH `memories` and `core_facts`. Toggling a class
  OFF only stops *future* collection; it never surprise-deletes. Purge is the separate
  opt-in for removing what's already there.
- `GET  /api/memory-center/export?format=md|json` — readable export. Default `md`
  (Markdown, grouped by category/sensitivity); `json` optional.

## 6. Frontend (extend `MemoryDashboard.tsx` → Memory Control Center)

Three sections, reachable by all signed-in users from settings:

- **Memories** — browse / edit / delete; each memory shows its sensitivity tag.
- **Privacy** — the 9-tag toggle list (excluding `none`) for disabling classes, plus a
  "Pause all memory collection" switch (optional auto-resume duration), plus per-class
  "Delete existing" (calls purge, with confirm).
- **Export** — a download button (Markdown).

## 7. Tier gating

Control/privacy endpoints move from `require_premium` → `verify_token` (everyone).
Optional paid flourishes (AI auto-categorization backfill) may remain premium.

## 8. Error handling & safety

- All reads/writes/deletes scoped to `user_id` (existing pattern; never trust a
  client-supplied user_id).
- Collection gate fails **open** (collect + log) on a settings-read error.
- Purge and pause are explicit user actions; toggling a class OFF never deletes existing
  data without a separate confirmed purge.
- Settings are cached per-user to avoid a DB read on every extraction.

## 9. Testing

- `should_collect`: paused → skip; disabled class → skip; enabled class → save;
  settings-read error → fail open.
- Sensitivity classifier: returns a valid tag or `none`; piggybacks extraction.
- Endpoints: settings update, per-user scoping (cannot touch another user's data),
  purge deletes only the targeted class, export formatting (md/json).
- Regression: existing dashboard edit/delete/lock behavior still works.

## 10. Explicitly out of scope (Phase B / fast-follow)

- "Why was this memory used in a response" (provenance tracking).
- Confidence disclosure ("I may remember this incorrectly") and conflict resolution
  (`newest confirmed > newest inferred > older`).
- Conversational "forget that we talked about X" (reuses Phase A APIs + confirmation).
- Governing graphiti / future-memory stores beyond the shared gate (add if trivial).
```
