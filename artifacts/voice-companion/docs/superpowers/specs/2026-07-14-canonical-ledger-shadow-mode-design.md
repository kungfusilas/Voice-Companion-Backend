# Canonical Ledger — Shadow Mode Design

**Date:** 2026-07-14
**Status:** Approved (design), pending implementation plan
**Scope:** Phase 1 of canonical-ledger productionization — *shadow mode only*

## Goal

Run the canonical-fact ledger (`app/canonical/` engine, already merged) against **real production traffic**, side-by-side with the existing `user_core_facts` extraction, so we can observe and adjudicate what the ledger *would have decided* — without changing a single byte of what any user sees. This phase produces evidence, not behavior.

## Governing invariants

1. **Inert toward the user.** `user_core_facts` and `memories` remain the sole source of truth for prompts, retrieval, exports, and the Memory Control Center. No prompt, retrieval path, companion, or user-facing surface reads `canonical_facts` in this phase.
2. **Legacy path is authoritative and unblocked.** The legacy write succeeds or fails exactly as it does today. The shadow path runs *after* it and can never delay, alter, or fail the user's turn. Fail-**open** toward the user (deliberately the opposite of the Stripe webhook, which is fail-closed: there correctness beats availability; here the live path's availability beats the shadow's completeness).
3. **The engine decides truth; the database enforces atomicity.** The Python engine in `app/canonical/` (benchmark-covered) is the single source of truth for *what* the ledger decides. The database is a dumb, race-safe applicator of a precomputed delta. No truth logic lives in SQL or in the mapper.
4. **Backward-compatible extraction schema.** The extended extraction prompt must remain backward-compatible with the legacy projection: legacy reads only `category`/`fact`/`sensitivity`; a missing or invalid `canonical` object never invalidates the legacy fact.
5. **Privacy gating precedes all persistence.** `memory_settings.should_collect` gates before *any* shadow write — `canonical_facts`, `canonical_fact_events`, divergence values, sampled agreements, and logs.

## Non-goals (explicitly deferred to later specs)

- **Backfill** — replaying historical `user_core_facts` into the ledger.
- **Activation** — the ledger serving any read path.
- **Retiring `user_core_facts`.**
- **`canonical_fact_heads`** revision table — added later only if multi-fact decisions, snapshot-conflict rates, or active-fact load cost demand it.
- **Durable retry queue** (roadmap item #1) — shadow processing is best-effort + gracefully drained, not durably queued (see §"Durability posture").
- **User-facing canonical reads** of any kind.

---

## Architecture

```
chat turn ─┐
           ├─▶ [legacy] extract_and_save_core_facts ──▶ user_core_facts   (UNCHANGED, authoritative)
           │        │ (same Haiku call, now emits a nested `canonical` object too)
           │        │ returns LegacyOutcome{status, inserted, existing}   (no more early-returns)
           │        ▼
           └─▶ [shadow] shadow_ledger.run(facts, legacy_outcome, exchange_id)   ALWAYS runs
                    ├─ privacy gate (should_collect) BEFORE any write
                    ├─ map → Candidate(s)              (curated registry + freeform fallback)
                    ├─ load active facts for each slot  ─┐
                    ├─ apply_candidate (pure engine)     ├─ engine = single source of truth
                    ├─ compute delta                    ─┘
                    ├─ persist via delta-RPC            (snapshot-match CAS; delta + events atomic)
                    ├─ classify + record divergence ──▶ ledger_shadow_divergences (semantic)
                    └─ write run receipt ─────────────▶ ledger_shadow_runs (operational + denominator)
```

**Hook point:** the `extract_and_save_core_facts` background task ([chat.py:1190](../../../app/routers/chat.py), also the streaming handler at chat.py:1476), scheduled via the `_bg` machinery hardened in PR #5.

---

## Component 1 — Extraction (piggyback, nested, backward-compatible)

The existing `_CORE_FACTS_SYSTEM` prompt is extended so the **same Haiku call** additionally emits a nested `canonical` object per fact. No new LLM call, no added latency.

```json
{
  "category": "location",
  "fact": "Lives in Easton, Pennsylvania",
  "sensitivity": "none",
  "canonical": {
    "subject_type": "user",
    "subject_id": "self",
    "predicate": "home_city",
    "value_json": { "city": "Easton", "state": "Pennsylvania" },
    "confidence": 0.97,
    "observed_at": "2026-07-14",
    "valid_from": "2026-06-01"
  }
}
```

- **Legacy parser reads only** `category`, `fact`, `sensitivity` — unchanged validation and write.
- **Shadow parser reads only** `canonical`. A missing/invalid/partial `canonical` → the fact is still written by legacy, and the shadow path records an `unmapped` outcome for that fact.
- **Token ceiling raised** from 400 (the current cap) to accommodate the extra fields without truncation.

### Generation-isolation caveat & deploy gate

Nesting isolates **parsing**, not **generation**: it is one forward pass, so a richer instruction can shift the legacy `category`/`fact`/`sensitivity` fields even though the parser ignores `canonical`. Therefore the extended prompt ships **only if it passes a corpus A/B gate**:

- Run old vs. new prompt against a fixed, checked-in corpus of representative turns.
- Compare, per prompt: legacy fact-capture rate, fact precision, category distribution, sensitivity distribution, JSON-parse-failure rate, mean facts/turn.
- **Hard gate:** if any legacy metric moves beyond a pre-registered threshold, we do **not** piggyback — we fall back to a **separate second Haiku call** for the canonical object (reversing the piggyback decision). Piggyback is the default; the A/B result is what earns it.

`observed_at` (when the user said it) is distinct from `valid_from` (when the fact became true) — both are captured; the engine already handles out-of-order `valid_from` (benchmark scenario 10).

---

## Component 2 — Predicate registry

Extend `app/canonical/registry.py` (today just `_MULTI = {children, pets, hobbies}`) into a curated registry:

- **~20 seed canonical predicates** (e.g. `home_city`, `employer`, `job_title`, `partner`, `children`, `pets`, `birthday`, `dietary_restriction`, `hobbies`, `pronouns`, …), each with:
  - **cardinality** ∈ `single` | `multi` | `unknown`
  - an **alias map** applied at map-time (`city_of_residence`, `lives_in` → `home_city`) so fragmentation cannot occur
  - a short **value-shape hint** injected into the extraction prompt
- **Freeform predicates** outside the registry are allowed but assigned cardinality `unknown`.

### `unknown` cardinality — accumulate, never supersede

New engine behavior (a change to the **merged** `app/canonical/` engine): an `unknown`-cardinality candidate **accumulates and deduplicates identical values but never supersedes a differing value**, and is stored `status='active'` but flagged for registry review. This prevents `friend=Susan` → `friend=Michael` from destructively superseding. Registry promotion (`unknown → single|multi`) happens later as real traffic reveals cardinality; promotion never retroactively rewrites historical rows (cardinality is snapshotted per row — see §Data model).

**Engine change requires a new benchmark scenario:** `13_unknown_predicate_no_supersede.yaml` (two differing values under an unknown predicate both remain active; an identical repeat dedups). Existing 12 scenarios must stay green.

---

## Component 3 — Data model

### `canonical_facts` — the ledger (versioned store)

Columns mirror the `Fact` dataclass plus production essentials:

| column | notes |
|---|---|
| `id` | uuid pk |
| `owner_user_id` | account owner; partition/index key |
| `subject_type` | `user` \| `companion` \| … |
| `subject_id` | usually `self` |
| `predicate` | canonical or freeform |
| `cardinality` | **stored** `single`\|`multi`\|`unknown`, snapshotted from registry at write |
| `value_json` | jsonb |
| `normalized_value` | case/order-insensitive canonical string |
| `sub_key` | entity key for multi-valued (e.g. child name), else null |
| `status` | `active`\|`superseded`\|`deleted`\|`expired`\|`unconfirmed` |
| `scope` | `global`\|`companion`\|`session`\|`vault` |
| `companion_id` | nullable |
| `valid_from`, `valid_until` | when the fact is true |
| `observed_at` | when the user stated it (≠ `valid_from`) |
| `supersedes_fact_id` | nullable self-fk |
| `confirmation_status` | `inferred`\|`explicitly_stated`\|`user_confirmed`\|`user_corrected`\|`disputed` |
| `sensitivity` | tag from `memory_settings.SENSITIVITY_TAGS` |
| `version` | int, optimistic-concurrency guard |
| `extractor_version`, `mapper_version`, `engine_version`, `registry_version` | provenance quad |
| `decision_reason` | short code from the engine |
| `source_exchange_id` | minted per turn (see §Execution) |
| `created_at`, `updated_at` | timestamptz |

**Three partial unique indexes (the DB mirror of the cardinality registry):**

```sql
CREATE UNIQUE INDEX one_active_single ON canonical_facts
  (owner_user_id, subject_type, subject_id, predicate, scope,
   COALESCE(companion_id,'∅'), COALESCE(sub_key,''))
  WHERE status='active' AND cardinality='single';

CREATE UNIQUE INDEX one_active_multi ON canonical_facts
  (owner_user_id, subject_type, subject_id, predicate, scope,
   COALESCE(companion_id,'∅'), sub_key)
  WHERE status='active' AND cardinality='multi';

CREATE UNIQUE INDEX one_active_unknown ON canonical_facts
  (owner_user_id, subject_type, subject_id, predicate, scope,
   COALESCE(companion_id,'∅'), normalized_value)
  WHERE status='active' AND cardinality='unknown';
```

**Load index:** `(owner_user_id, subject_type, subject_id, predicate, scope, companion_id, sub_key, status)`.
**Supporting indexes:** `supersedes_fact_id`, `normalized_value`, `extractor_version`, `created_at`.
**Idempotency:** unique on `(owner_user_id, source_exchange_id, predicate, scope, COALESCE(companion_id,'∅'), normalized_value, extractor_version)` — replays of the same background task don't double-apply.
**RLS:** service-key only; no user-facing reads this phase.

### `canonical_fact_events` — append-only audit/rebuild seam

Written inside the delta-RPC transaction (see §Concurrency). Records *why* each decision happened — irrecoverable after the fact.

| column | notes |
|---|---|
| `id`, `owner_user_id`, `source_exchange_id`, `candidate_id` | |
| `event_type` | `candidate_received`\|`fact_created`\|`fact_deduped`\|`fact_superseded`\|`fact_deleted`\|`fact_expired`\|`candidate_rejected`\|`candidate_unconfirmed`\|`apply_conflict` |
| `fact_id`, `related_fact_id`, `predicate` | |
| `engine_version`, `mapper_version`, `extractor_version`, `registry_version` | |
| `decision_reason` | short code |
| `payload_json` | **restrained** — identifiers, normalized values, prev/new status, decision code, versions, scope/sensitivity metadata; **never** raw conversation or sensitive text |
| `created_at` | |

At minimum, append an event for **every state-changing decision**. `candidate_received` may be sampled if volume demands. Sensitive-tagged facts get **metadata-only** payloads. Example payload:

```json
{ "reason": "single_value_changed",
  "previous_normalized_value": "bethlehem|pennsylvania",
  "new_normalized_value": "easton|pennsylvania",
  "expected_previous_version": 3 }
```

### `ledger_shadow_divergences` — the proof surface (semantic disagreements only)

One row per *interesting* comparison; agreements are counted, not stored (plus a small sample — see rollup).

- `id`, `owner_user_id`, `occurred_at`, `subject_type`, `subject_id`, `predicate`
- `kind` — **open documented string** (not a DB enum, so new kinds need no migration): `supersede_caught`, `contradiction`, `only_in_ledger`, `only_in_legacy`, `legacy_duplicate`, `legacy_cap_blocked`, `scope_mismatch`, `sensitivity_mismatch`, `unmapped`
- `ledger_value` (jsonb), `legacy_value` (jsonb), `detail` (jsonb)
- Gated content stores **no value** — only `kind` + `sensitivity` metadata.

### `ledger_shadow_runs` — per-turn receipt (operational outcomes + the denominator)

Distinguishes "agreed" from "never ran," which the divergence table alone cannot.

- `id`, `source_exchange_id`, `owner_user_id`
- `extractor_version`, `mapper_version`, `engine_version`, `registry_version`
- `started_at`, `completed_at`, `duration_ms`
- `status` — `completed`\|`no_candidates`\|`privacy_gated`\|`legacy_capped`\|`legacy_error`\|`parse_error`\|`shadow_timeout`\|`shadow_error`\|`concurrency_retry_exhausted`
- `candidate_count`, `agreement_count`, `divergence_count`, `legacy_insert_count`, `ledger_mutation_count`
- `error_code` (nullable)
- **Unique constraint:** `(source_exchange_id, extractor_version)`.

**Operational failures** (`extract_parse_error`, `legacy_write_error`, `mapper_error`, `ledger_load_error`, `ledger_persist_error`, `shadow_timeout`, `concurrency_conflict`) live here — **not** in the divergence table.

### `ledger_shadow_daily_rollup` — aggregate metrics

Upserted daily, keyed by `(date, extractor_version, mapper_version, engine_version)`:
`attempted_runs`, `completed_runs`, `missing_runs`, `candidate_count`, `agreement_count`, `divergence_count` (+ by-kind jsonb), `gated_count`, `parse_error_count`, `legacy_error_count`, `shadow_error_count`, `timeout_count`.

A candidate is **comparable** when it mapped successfully (not `unmapped`) *and* the legacy outcome for the same slot is known — so the ledger's and legacy's states can be directly compared. Candidates that were unmapped, gated, or lost to an operational failure are **not** comparable.

**The reported metric is not `agreements / divergences`.** It is:
- `agreement_rate = agreements / comparable candidates`, shown **alongside**
- `comparability_rate = comparable candidates / total extraction opportunities`

so a system silently failing half its turns cannot hide behind a high agreement rate. A **0.5–1% random sample of agreements** is retained (subject to gating) specifically to catch bugs in the comparator that would otherwise inflate the agreement rate invisibly.

---

## Component 4 — Concurrency & persistence (delta-RPC + CAS)

The engine produces a **delta** in Python (facts to supersede/delete by id + expected version, rows to insert). A single Supabase RPC applies it in one transaction:

**RPC invariant:** *Either the expected snapshot still matches — every targeted fact still at its expected version/status — and the complete delta plus its audit events commit together; or nothing changes and the caller reruns `apply_candidate` against fresh state.*

- Conditional updates (supersede/delete only if still `active` at expected `version`); inserts of new `active` rows; `canonical_fact_events` appends — all in the one transaction.
- The **partial unique indexes** are the backstop: a concurrent double-insert of a second `active` row for the same slot violates the index and aborts the transaction → caller reloads and reruns.
- **Retry-on-conflict** with a small bounded retry count; exhaustion → `ledger_shadow_runs.status='concurrency_retry_exhausted'` (recorded, never raised into the chat path).
- A per-user in-process `asyncio.Lock` reduces self-contention within the single instance, but **correctness is carried entirely by the DB** (safe across overlapping deploys, replay/reconcile workers, and any future multi-worker).

`canonical_fact_heads` (a per-slot revision record) is **deferred**; introduce it only if multi-fact-per-decision reconciliation, snapshot-conflict rates, or active-fact load cost become real.

---

## Execution flow & integration

1. **Mint `exchange_id`** (uuid) once per turn in the chat handler. Neither `source_exchange_id` nor `source_message_id` exists today — `extract_and_save_core_facts` receives only `(user_id, message, reply)` and `save_exchange` appends into a session-keyed jsonb array with only a `ts`. The minted `exchange_id` is threaded to the shadow runner (receipt PK + idempotency) **and** added as an `id` on each archived message dict (a one-line addition to `save_exchange`) so a nightly job can reconcile archived exchanges against receipts.
2. **Refactor `extract_and_save_core_facts`** to stop early-returning. It performs the (unchanged) legacy write and returns a `LegacyOutcome{status ∈ inserted|duplicate|capped|gated|error, inserted_facts, existing_facts}`. The cap-blocked and dedup paths — where the ledger most often reveals legacy weakness — are now reported, not swallowed.
3. **Always call the shadow runner**, wrapped:

```python
legacy_outcome = await run_legacy_write(facts=facts, settings=settings)
try:
    await asyncio.wait_for(
        shadow_ledger.run(facts=facts, legacy_outcome=legacy_outcome,
                          source_exchange_id=exchange_id),
        timeout=SHADOW_TIMEOUT_SECONDS,
    )
except Exception:
    logger.exception("shadow ledger failed")  # never propagates to the turn
```

The user experiences nothing different regardless of shadow outcome.

### Durability posture

Shadow processing is **best-effort + gracefully drained** (PR #5's `_bg` tracking gives ≤10s on shutdown) — **not** durably queued. That is acceptable for an invisible system. The `ledger_shadow_runs` receipt is what makes the *evaluation* sound: without it, "agreed," "never ran," "crashed before shadow," and "timed out during shutdown" are indistinguishable.

---

## Privacy & data lifecycle

- **Gate before any persistence.** `should_collect` runs before writing `canonical_facts`, `canonical_fact_events`, divergence values, sampled agreements, or logs. Gated content → `ledger_shadow_runs.status='privacy_gated'` and, where a divergence is still worth noting, only `kind` + `sensitivity` metadata (never the value). Raw structured Haiku output is never logged when it may contain sensitive text.
- **Retention.** Detailed divergence values and event payloads that duplicate user facts are retained **30–90 days**, after which only aggregate rollups survive. Sensitive-tagged rows may warrant shorter retention / metadata-only payloads.
- **Deletion.** Extend the existing GDPR erasure endpoint `delete_account` ([account.py:166](../../../app/routers/account.py)) to also purge `canonical_facts`, `canonical_fact_events`, `ledger_shadow_divergences`, and `ledger_shadow_runs` for the user.
- **Admin endpoint.** Read-only, requires **actual administrator authorization** (not mere possession of a valid app token). Serves per-case divergence detail + aggregate rates. This is the only read path in this phase.

---

## Error handling

| failure | handling |
|---|---|
| extraction parse error | legacy handles as today; `runs.status=parse_error` |
| legacy write error | `LegacyOutcome.status=error`; shadow still runs & compares; `runs` records it |
| mapper/load/persist error | swallowed from the turn; `runs.status=shadow_error`, `error_code` set |
| shadow timeout | `runs.status=shadow_timeout` |
| concurrency conflict | bounded retry; exhaustion → `concurrency_retry_exhausted` |
| privacy gated | `runs.status=privacy_gated`, no value persisted |

No shadow failure ever raises into the chat request path.

---

## Testing strategy

**Offline / deterministic (no prod, no LLM):**
- Engine: existing 12 benchmark scenarios stay green + new `13_unknown_predicate_no_supersede`.
- Registry: alias normalization, cardinality lookup, unknown fallback.
- Mapper: nested `canonical` → `Candidate`; missing/partial `canonical` → `unmapped`.
- Delta computation + CAS: simulated snapshot-mismatch forces a rerun; simulated double-insert is caught by the partial unique index; idempotent replay of the same `exchange_id` is a no-op.
- Divergence classifier: each `kind` produced from crafted legacy-vs-ledger states, including a seeded false-agreement to prove the comparator/sample catches it.
- Privacy gating: gated sensitivity writes nothing but the aggregate.

**A/B corpus harness (deploy gate):** old vs. new prompt over a checked-in corpus; asserts legacy metrics stay within pre-registered thresholds.

**Integration (staging):** a turn produces exactly one `ledger_shadow_runs` row; deletion test proves all four tables are purged by `delete_account`.

---

## Build sequence (informs the plan's task order)

1. **Offline spine** — registry expansion + engine `unknown` cardinality + scenario 13; mapper; delta/CAS logic; all unit + benchmark tested, **zero prod wiring**.
2. **Schema** — the four tables, indexes, constraints, delta-RPC + events append (migration).
3. **Live wiring** — nested prompt behind the A/B gate; `LegacyOutcome` refactor; `exchange_id` minting; always-run shadow with timeout + gating.
4. **Observability** — receipts, divergence recording, daily rollup + sampling, admin endpoint.
5. **Privacy/lifecycle** — retention job + `delete_account` extension + admin authz.

Each stage is independently reviewable; stage 1 is fully provable before anything touches production.

---

## Success / exit criteria (what graduates shadow → activation, a later spec)

- The extended prompt passed the A/B gate (no legacy-behavior regression).
- Ledger runs on ~100% of eligible traffic for a sustained window with `shadow_error`/`concurrency_retry_exhausted` rates below a set threshold.
- `comparability_rate` above a set threshold (the ledger is actually structuring facts, not silently failing).
- Manual adjudication of a divergence sample shows the ledger is **right** in the disagreements (especially `supersede_caught` / `legacy_cap_blocked`).
- Deletion + retention verified end-to-end.
