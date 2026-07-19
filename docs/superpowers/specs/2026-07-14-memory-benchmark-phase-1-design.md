# Memory Benchmark — Phase 1 (Deterministic Foundation) Design

Date: 2026-07-14
Status: Design approved; pending spec review → implementation plan
Scope: Phase 1 (v1) only. Later layers (B/C/D/A2/scale/episodic) are follow-on slices.

## 1. Purpose

Build the measuring stick for LegacyBond's long-term memory **before** re-architecting
the memory system, so every subsequent change is provably better and never regresses
trust. The benchmark is the **executable contract** for a trustworthy multi-year memory:
it encodes what should be remembered, updated, forgotten, and never recalled, and scores
the system against a fixed **gold memory timeline**.

Governing principle (adopted): **the LLM may propose memories, but the canonical engine
decides what becomes truth.** The benchmark tests the engine's decisions, not the model's
whims.

The benchmark and the memory **ledger** are two coupled projects:
- **This spec** = the benchmark (the contract).
- **The ledger** (`canonical_facts` engine + its staged rollout) = the implementation that
  grows to pass the benchmark. That rollout is its own spec (the immediate follow-on).

## 2. Scope

**In (Phase 1):**
- The **gold memory timeline** format (YAML) + loader/validator — the single source of truth.
- The **adapter contract** the benchmark talks to (stable seam; v1 exercises two verbs).
- The **runner + report + hard-gate mechanism** (Layer E gates can fail the whole run).
- **Layer A1** — deterministic lifecycle scenarios (~12) fed *recorded structured
  extraction candidates*, asserting on the resulting canonical state.
- A **minimal `canonical_facts` engine** (pure lifecycle logic + predicate registry) that
  A1 drives red→green. This is the first brick of the ledger.

**Out (each a later slice):**
- **Layer B** retrieval quality (required/helpful/forbidden sets, Recall@K, etc.).
- **Layer C** end-to-end response (deterministic answer checks + LLM judge for softness).
- **Layer D** durability / rebuild-equivalence.
- **Layer A2** live-extraction (real model on the utterances; nightly).
- Degradation-at-scale curves (10 → 50k memories).
- **Episodic/emotional memory** modeling (v1 ledger = canonical *facts*/propositions only).

The gold-timeline format is designed from day one to carry the data these later layers need
(queries, expected answers, recorded utterances), so adding them never reworks Phase 1.

## 3. The gold memory timeline (source of truth)

One YAML file per scenario under `benchmark/scenarios/`. The *same* timeline drives every
layer (A1 now; A2/B/C/D later), which prevents the suites from drifting apart.

```yaml
scenario: user_moves_and_requests_forgetting
description: single-valued fact supersession + explicit forgetting
events:
  - time: "2026-01-10"
    companion: aeva
    user: "I live in Bethlehem, Pennsylvania."
    # A1 feeds this recorded candidate to the engine. A2 (later) ignores it and
    # runs live extraction on `user`, comparing to the same expectations.
    extraction:
      - subject_type: user
        predicate: home_city
        value_json: {city: "Bethlehem", state: "Pennsylvania"}
        confirmation_status: explicitly_stated
        valid_from: "2026-01-10"
  - checkpoint: after_initial_location
    expected_active:
      - key: user.home_city
        value: {city: "Bethlehem", state: "Pennsylvania"}
        scope: global
  - time: "2027-04-15"
    companion: aeva
    user: "I moved to Easton last month."
    extraction:
      - subject_type: user
        predicate: home_city
        value_json: {city: "Easton", state: "Pennsylvania"}
        confirmation_status: user_corrected
        valid_from: "2027-03-15"
  - checkpoint: after_move
    expected_active:
      - key: user.home_city
        value: {city: "Easton"}
    expected_superseded:
      - key: user.home_city
        value: {city: "Bethlehem"}
  - time: "2027-05-01"
    companion: aeva
    user: "Forget where I live."
    control: {op: forget, key: user.home_city}
  - checkpoint: after_forgetting
    expected_absent:
      - key: user.home_city
# queries: [...]  # present in the format now; consumed by Layers B/C later
```

Event kinds: `time`+`user`(+`extraction`) (a turn), `checkpoint` (assertion point),
`control` (a user command such as forget/confirm/toggle-category). Assertions at a
checkpoint: `expected_active`, `expected_superseded`, `expected_absent`,
`expected_state` (for other lifecycle states).

In assertions, `key` is shorthand for `<subject_type>.<predicate>` (e.g. `user.home_city`),
which the engine matches to the stored `subject_type` + `predicate` (+ `sub_key` for
multi-valued predicates). Value comparison is against `normalized_value`, so a
`{city: "Easton"}` expectation matches regardless of surrounding phrasing.

## 4. The `canonical_facts` model (adopted)

Schema the engine writes and the benchmark asserts on (behavioral assertions preferred;
internal columns may evolve behind the adapter):

```
canonical_facts
  id, user_id
  subject_type, subject_id
  predicate
  value_json            -- structured (do not flatten to text)
  normalized_value      -- for deterministic comparison / search
  status                -- active | superseded | deleted | expired | unconfirmed
  scope                 -- global | companion | session | vault
  companion_id          -- set when scope=companion
  valid_from, valid_until
  supersedes_fact_id
  source_message_id, source_conversation_id
  confidence
  confirmation_status   -- inferred | explicitly_stated | user_confirmed | user_corrected | disputed
  sensitivity           -- reuses Phase-A tag set
  recall_policy         -- normal | only_when_relevant | only_when_user_mentions_topic | never_proactively_recall | vault_only
  extractor_version
  created_at, updated_at
```

### Predicate registry (cardinality — the key correctness rule)

A separate registry declares each predicate's cardinality; the engine uses it to decide
identity for supersession vs. accumulation:
- **single-valued** (`home_city`, `employer`, `marital_status`): identity = `(subject, predicate, scope)`. A new value **supersedes** the prior active one.
- **multi-valued** (`children`, `pets`, `hobbies`): identity = `(subject, predicate, scope, sub_key)` (e.g. child-by-name). New distinct entries **accumulate**; a repeat of the same sub_key **dedupes**.

This is what prevents both wrong-supersession ("second child replaces first") and
wrong-duplication ("ten mentions → ten facts").

## 5. Engine contract + adapter

The engine's lifecycle logic is a **pure function** over in-memory state so A1 is
deterministic and needs no database (mirrors the Phase-A `should_collect` approach):

```
apply_candidate(facts: list[Fact], candidate: Candidate, registry, now) -> list[Fact]
apply_control(facts: list[Fact], control: Control, now) -> list[Fact]   # forget/confirm/...
active_facts(facts: list[Fact], scope, at_time) -> list[Fact]
```

Persistence (Supabase `canonical_facts`) is a thin separate layer, not tested by A1.

The **benchmark adapter** wraps the engine behind a stable interface so the architecture
can evolve without rewriting scenarios:
- `apply_events(timeline) -> state` (v1: runs each event's `extraction`/`control` through the engine)
- `active_facts(scope, at_time) -> [facts]` (v1: for checkpoint assertions)
- `retrieve(query, k)`, `answer(query)`, `rebuild()` — declared now, stubbed until B/C/D slices.

## 6. Layer A1 — deterministic lifecycle scenarios (~12)

A1 feeds recorded, well-formed candidates to the engine and asserts the resulting canonical
state at each checkpoint. It does **not** call an LLM (extraction quality is A2). Coverage:

1. Upsert a new single-valued fact → active.
2. Supersession: new value for a single-valued predicate → old superseded, new active, `supersedes_fact_id` set.
3. Accumulation: two distinct multi-valued entries (two children) → both active, neither superseded.
4. Dedup (single): ten identical mentions → one active fact.
5. Dedup (multi): repeat of the same sub_key → one entry, not two.
6. Distinct-not-merged: two similar-but-different multi-valued entries stay separate.
7. Forget: `control: forget` → fact `deleted`/absent from active.
8. Scope isolation: a `companion`-scoped fact is absent from a different companion's `active_facts`; a `global` fact is visible to all.
9. Idempotency: applying the same candidate/event twice → identical state (no dup active fact, no doubled confidence).
10. Temporal / out-of-order: a correction with an earlier `valid_from` applied *after* the original still yields the correct current value (ordering by `valid_from`, not apply order).
11. Confirmation precedence: `user_confirmed`/`user_corrected` outranks a conflicting `inferred` candidate.
12. Expiry: a temporary fact with `valid_until` in the past → `expired`, absent from active.

Each scenario = one gold-timeline file; A1 asserts `expected_active/superseded/absent/state`
at each checkpoint. Pass/fail is deterministic.

## 7. Layer E — hard gates (from day one)

Baked into the runner now, even though the full adversarial/isolation suites grow later.
Any occurrence **fails the entire run** (never averaged into a score):
- A `companion`-scoped fact appearing in another companion's `active_facts`.
- A `deleted` fact appearing as active (deleted-memory resurfacing).
- A fact the timeline marked prohibited (`never remember`) present in the store.
- (Cross-user leakage / export leakage / prompt-injection-as-instruction: gate hooks
  declared now; populated as B/D slices land.)

## 8. Scoring & report

- **A1:** per-scenario pass/fail; report lists each scenario, each failed assertion (expected
  vs. actual canonical state).
- **E gates:** hard fail — if any gate trips, the run is failed regardless of A1 pass rate.
- **Report:** a summary (A1 pass count, gate status) written to stdout and a JSON artifact
  (`benchmark/results/<timestamp>.json`) so later slices can track trends/baselines.
- Latency/cost/personality are **not** in the correctness score (reported separately later).

## 9. Location, tooling, how it runs

- Engine: `artifacts/voice-companion/app/canonical/engine.py` (pure logic),
  `registry.py` (predicate cardinality), `store.py` (Supabase persistence, later).
- Benchmark: `artifacts/voice-companion/benchmark/` — `scenarios/*.yaml`, `adapter.py`,
  `runner.py`, `loader.py`, `results/`.
- Tests: `artifacts/voice-companion/tests/` (pytest, via `requirements-dev.txt`).
- **Runs on every PR** (fast, deterministic — no LLM, no live DB). Invocation:
  `python -m pytest tests/ -q` plus `python -m benchmark.runner` for the scenario report.

## 10. Determinism

Phase-1 A1 has **no LLM and no live database** — pure engine logic over YAML fixtures — so
it is a reliable CI gate. LLM variance is confined to the later A2/C slices, which run
nightly/pre-release with pinned model versions, temperature 0 where possible, and multi-run
aggregation.

## 11. Relationship to the ledger-rollout spec (sibling)

The minimal engine here is Phase 1 of the ledger. The full ledger productionization —
async extraction pipeline (LLM proposes → validate/normalize → contradiction engine →
`canonical_facts`), shadow mode, careful backfill (reprocess source conversations; legacy
rows imported as low-authority `inferred_legacy`), shadow retrieval, gradual activation
behind hard gates, and retiring `user_core_facts` via a compat view — is its **own spec**,
written next, and gated by this benchmark as it grows (B/D/E slices).
