# Canonical Ledger Shadow Mode — Plan 1: Offline Spine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the canonical engine production-capable — curated predicate registry, safe `unknown` cardinality, extraction→Candidate mapper, and before/after→delta computation — all pure, unit- and benchmark-tested, with **zero production wiring**.

**Architecture:** This is Stage 1 of 5 in the shadow-mode rollout (spec: `docs/superpowers/specs/2026-07-14-canonical-ledger-shadow-mode-design.md`). It extends the merged `app/canonical/` engine and adds two new pure modules (`mapper`, `delta`) plus a new benchmark scenario. Nothing here touches Supabase, the LLM, or any router — later plans (schema → live wiring → observability → privacy) build on these seams. Every artifact is deterministic and offline-provable.

**Tech Stack:** Python 3, dataclasses, pytest, the existing `benchmark/` harness (YAML scenarios + runner). No new dependencies.

## Global Constraints

- **No DB, no LLM, no network, no router changes.** Pure functions and dataclasses only.
- **All existing tests stay green.** `python -m pytest tests/ -q` (currently 31 passed) and `python -m benchmark.runner` (currently `A1: 12/12`) must remain green after every task.
- **Cardinality preservation:** the predicates the existing scenarios rely on must keep their current effective cardinality — `home_city`, `current_trip`, `therapy_note` are **single**; `children` is **multi**. Only genuinely-unregistered predicates become `unknown`.
- **The engine decides truth.** No lifecycle logic moves out of `app/canonical/engine.py`.
- Run all commands from `artifacts/voice-companion/`.

---

## File Structure

- Modify `app/canonical/registry.py` — curated registry: `_SINGLE`, `_MULTI`, `_ALIASES`, `_VALUE_HINTS`; `cardinality` returns `single|multi|unknown`; add `canonical_predicate`, `is_registered`, `value_hint`.
- Modify `app/canonical/models.py` — add `cardinality` + `observed_at` to `Fact`, `observed_at` to `Candidate`, and a `CONFIRMATION_STATUSES` constant.
- Modify `app/canonical/engine.py` — `identity` gains an `unknown` branch (discriminate by `normalized_value`); `apply_candidate`/`_new_fact` carry `cardinality` and a multi-only `sub_key`.
- Create `app/canonical/mapper.py` — `map_canonical(obj, sensitivity, now) -> Candidate | None`.
- Create `app/canonical/delta.py` — `Delta` dataclass + `compute_delta(before, after, *, engine_version, candidate_id) -> Delta`.
- Create `benchmark/scenarios/13_unknown_predicate_no_supersede.yaml`.
- Modify `tests/test_canonical_engine.py` — add `unknown` cardinality unit tests.
- Create `tests/test_registry.py`, `tests/test_mapper.py`, `tests/test_delta.py`.

---

### Task 1: Curated predicate registry

**Files:**
- Modify: `app/canonical/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces: `cardinality(predicate) -> "single"|"multi"|"unknown"`, `canonical_predicate(raw) -> str`, `sub_key(predicate, value_json) -> str|None`, `is_registered(predicate) -> bool`, `value_hint(predicate) -> str|None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_registry.py`:

```python
from app.canonical import registry as reg


def test_registered_single_and_multi():
    assert reg.cardinality("home_city") == "single"
    assert reg.cardinality("children") == "multi"


def test_scenario_predicates_keep_current_cardinality():
    # These are relied on by existing benchmark scenarios and were "single" by default.
    for p in ("home_city", "current_trip", "therapy_note"):
        assert reg.cardinality(p) == "single"


def test_unregistered_predicate_is_unknown():
    assert reg.cardinality("friend") == "unknown"
    assert reg.cardinality("favorite_conspiracy_theory") == "unknown"


def test_alias_resolves_before_cardinality():
    assert reg.canonical_predicate("city_of_residence") == "home_city"
    assert reg.canonical_predicate("lives_in") == "home_city"
    assert reg.cardinality("city_of_residence") == "single"
    assert reg.canonical_predicate("unknown_thing") == "unknown_thing"


def test_sub_key_multi_only():
    assert reg.sub_key("children", {"name": "Emma"}) == "emma"
    assert reg.sub_key("home_city", {"city": "Easton"}) is None


def test_is_registered_and_value_hint():
    assert reg.is_registered("home_city") is True
    assert reg.is_registered("friend") is False
    assert "city" in reg.value_hint("home_city")
    assert reg.value_hint("friend") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_registry.py -q`
Expected: FAIL (`cardinality("friend")` returns `"single"`, `canonical_predicate` missing).

- [ ] **Step 3: Rewrite `app/canonical/registry.py`**

```python
"""Predicate registry: canonical names, aliases, cardinality, prompt value-shape hints.

Cardinality drives the engine lifecycle:
  single  — one active fact per slot; a new value supersedes the old.
  multi   — many active facts per slot, keyed by sub_key; each entry independent.
  unknown — freeform/unregistered predicate; accumulates and dedups identical
            values but NEVER supersedes a differing value (no destructive
            lifecycle decisions until cardinality is understood). Freeform
            predicates are registry-promotion candidates as traffic reveals them.
"""
from __future__ import annotations

# Multi-valued predicates: predicate -> the value_json field used as the entity key.
_MULTI: dict[str, str] = {
    "children": "name",
    "pets": "name",
    "hobbies": "name",
}

# Single-valued canonical predicates (one current value at a time).
# NOTE: current_trip and therapy_note are here to preserve existing benchmark
# scenarios, which relied on the old "single-by-default" behavior.
_SINGLE: frozenset[str] = frozenset({
    "home_city", "home_country", "employer", "job_title", "partner",
    "marital_status", "birthday", "dietary_restriction", "pronouns",
    "religion", "native_language", "school", "current_trip", "therapy_note",
})

# Raw predicate (as the LLM might emit) -> canonical predicate name.
_ALIASES: dict[str, str] = {
    "city_of_residence": "home_city", "lives_in": "home_city",
    "city": "home_city", "hometown": "home_city",
    "company": "employer", "workplace": "employer",
    "role": "job_title", "title": "job_title",
    "spouse": "partner", "husband": "partner", "wife": "partner",
    "significant_other": "partner",
    "kids": "children", "child": "children",
    "pet": "pets", "hobby": "hobbies",
    "diet": "dietary_restriction", "dietary_restrictions": "dietary_restriction",
}

# Short value-shape hints injected into the extraction prompt (canonical -> hint).
_VALUE_HINTS: dict[str, str] = {
    "home_city": '{"city": str, "state"?: str, "country"?: str}',
    "employer": '{"name": str}',
    "job_title": '{"title": str}',
    "partner": '{"name": str}',
    "children": '{"name": str, "age"?: int}',
    "pets": '{"name": str, "species"?: str}',
    "birthday": '{"date": "YYYY-MM-DD"}',
    "dietary_restriction": '{"restriction": str}',
    "pronouns": '{"pronouns": str}',
}


def canonical_predicate(raw: str) -> str:
    """Resolve an alias to its canonical predicate; unknown predicates pass through."""
    key = (raw or "").strip().lower()
    return _ALIASES.get(key, key)


def cardinality(predicate: str) -> str:
    p = canonical_predicate(predicate)
    if p in _MULTI:
        return "multi"
    if p in _SINGLE:
        return "single"
    return "unknown"


def sub_key(predicate: str, value_json: dict) -> str | None:
    field = _MULTI.get(canonical_predicate(predicate))
    if field is None:
        return None
    return str(value_json.get(field, "")).strip().lower()


def is_registered(predicate: str) -> bool:
    p = canonical_predicate(predicate)
    return p in _MULTI or p in _SINGLE


def value_hint(predicate: str) -> str | None:
    return _VALUE_HINTS.get(canonical_predicate(predicate))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_registry.py -q`
Expected: PASS.

- [ ] **Step 5: Verify existing suites still green**

Run: `python -m pytest tests/ -q && python -m benchmark.runner`
Expected: `31 passed` (plus the new registry tests) and `A1: 12/12 scenarios passed. Hard gates: clean.`

- [ ] **Step 6: Commit**

```bash
git add app/canonical/registry.py tests/test_registry.py
git commit -m "feat(canonical): curated predicate registry with unknown cardinality"
```

---

### Task 2: `unknown` cardinality in the engine + model fields + scenario 13

**Files:**
- Modify: `app/canonical/models.py`
- Modify: `app/canonical/engine.py`
- Create: `benchmark/scenarios/13_unknown_predicate_no_supersede.yaml`
- Test: `tests/test_canonical_engine.py` (add cases)

**Interfaces:**
- Consumes: `registry.cardinality`, `registry.sub_key` (Task 1).
- Produces: `Fact.cardinality`, `Fact.observed_at`, `Candidate.observed_at`, `models.CONFIRMATION_STATUSES`; `apply_candidate` treats `unknown`-cardinality candidates as accumulate-never-supersede.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_canonical_engine.py`:

```python
from datetime import date
from app.canonical.engine import apply_candidate, active_facts
from app.canonical.models import Candidate


def _friend(name):
    return Candidate(subject_type="user", predicate="friend",
                     value_json={"name": name}, confirmation_status="explicitly_stated")


def test_unknown_predicate_accumulates_never_supersedes():
    now = date(2027, 1, 1)
    facts = apply_candidate([], _friend("Susan"), now)
    facts = apply_candidate(facts, _friend("Michael"), now)
    active = active_facts(facts, now)
    names = sorted(f.value_json["name"] for f in active)
    assert names == ["Michael", "Susan"]  # both survive; no supersession


def test_unknown_predicate_dedups_identical_value():
    now = date(2027, 1, 1)
    facts = apply_candidate([], _friend("Susan"), now)
    facts = apply_candidate(facts, _friend("susan"), now)  # case-insensitive repeat
    assert len(active_facts(facts, now)) == 1


def test_fact_carries_cardinality_and_sub_key_semantics():
    now = date(2027, 1, 1)
    facts = apply_candidate([], _friend("Susan"), now)
    f = active_facts(facts, now)[0]
    assert f.cardinality == "unknown"
    assert f.sub_key is None  # unknown uses normalized_value, not sub_key column
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_canonical_engine.py -q`
Expected: FAIL (`Fact` has no `cardinality`; unknown predicate currently defaults to `single` and would supersede).

- [ ] **Step 3: Add model fields**

In `app/canonical/models.py`, add the constant near the top:

```python
CONFIRMATION_STATUSES = frozenset({
    "disputed", "inferred", "explicitly_stated", "user_confirmed", "user_corrected",
})
```

Add to `Fact` (after `sub_key`):

```python
    cardinality: str = "single"
    observed_at: date | None = None
```

Add to `Candidate` (after `confirmation_status`):

```python
    observed_at: date | None = None
```

- [ ] **Step 4: Update the engine**

In `app/canonical/engine.py`, replace `identity`:

```python
def identity(subject_type, subject_id, predicate, scope, companion_id, value_json, reg=registry) -> tuple:
    """Slot identity for supersession/dedup.
    single  -> value-independent (one slot per predicate)
    multi   -> keyed by sub_key (one slot per entity)
    unknown -> keyed by normalized_value (each distinct value is its own slot,
               so differing values accumulate and never supersede)."""
    card = reg.cardinality(predicate)
    if card == "multi":
        disc = reg.sub_key(predicate, value_json)
    elif card == "unknown":
        disc = normalize_value(value_json)
    else:
        disc = None
    return (subject_type, subject_id, predicate, scope, companion_id, disc)
```

Replace `_new_fact` to carry cardinality/observed_at:

```python
def _new_fact(cand: Candidate, now: date, status="active", supersedes=None,
              sub_key=None, cardinality="single") -> Fact:
    return Fact(
        id=str(uuid.uuid4()),
        subject_type=cand.subject_type, subject_id=cand.subject_id, predicate=cand.predicate,
        value_json=cand.value_json, normalized_value=normalize_value(cand.value_json),
        status=status, scope=cand.scope, companion_id=cand.companion_id,
        valid_from=cand.valid_from or now, valid_until=cand.valid_until,
        supersedes_fact_id=supersedes, confirmation_status=cand.confirmation_status,
        sensitivity=cand.sensitivity, sub_key=sub_key,
        cardinality=cardinality, observed_at=cand.observed_at,
    )
```

In `apply_candidate`, compute `card` + a multi-only stored sub_key and thread them into every `_new_fact` call:

```python
def apply_candidate(facts, cand: Candidate, now: date, reg=registry, prohibited=None):
    """Run a proposed fact through the lifecycle. Returns a NEW list; never mutates input."""
    facts = list(facts)
    if prohibited and f"{cand.subject_type}.{cand.predicate}" in prohibited:
        return facts
    card = reg.cardinality(cand.predicate)
    stored_sk = reg.sub_key(cand.predicate, cand.value_json) if card == "multi" else None
    ident = identity(cand.subject_type, cand.subject_id, cand.predicate, cand.scope,
                     cand.companion_id, cand.value_json, reg)
    norm = normalize_value(cand.value_json)
    peers = [
        f for f in facts
        if f.status == "active"
        and identity(f.subject_type, f.subject_id, f.predicate, f.scope, f.companion_id, f.value_json, reg) == ident
    ]
    if not peers:
        facts.append(_new_fact(cand, now, sub_key=stored_sk, cardinality=card))
        return facts
    cur = peers[0]
    if cur.normalized_value == norm:
        return facts
    cand_from = cand.valid_from or now
    if _CONFIRM_RANK[cand.confirmation_status] < _CONFIRM_RANK[cur.confirmation_status]:
        return facts
    if cur.valid_from and cand_from < cur.valid_from:
        facts.append(_new_fact(cand, now, status="superseded", sub_key=stored_sk, cardinality=card))
        return facts
    idx = facts.index(cur)
    facts[idx] = Fact(**{**cur.__dict__, "status": "superseded", "valid_until": cand_from})
    facts.append(_new_fact(cand, now, supersedes=cur.id, sub_key=stored_sk, cardinality=card))
    return facts
```

(Note: for `unknown` cardinality, differing values produce different `ident`, so `peers` is empty and the append branch runs — accumulate. Identical values hit the `cur.normalized_value == norm` dedup. The supersession branch is unreachable for `unknown`.)

- [ ] **Step 5: Create scenario 13**

Create `benchmark/scenarios/13_unknown_predicate_no_supersede.yaml`:

```yaml
scenario: unknown_predicate_no_supersede
description: an unregistered (unknown-cardinality) predicate accumulates differing values and never supersedes; identical repeats dedup
events:
  - time: "2027-01-01"
    companion: aeva
    user: "My friend Susan is great."
    extraction:
      - {subject_type: user, predicate: friend, value_json: {name: Susan}, confirmation_status: explicitly_stated}
  - time: "2027-01-02"
    companion: aeva
    user: "My friend Michael too."
    extraction:
      - {subject_type: user, predicate: friend, value_json: {name: Michael}, confirmation_status: explicitly_stated}
  - time: "2027-01-03"
    companion: aeva
    user: "Susan again."
    extraction:
      - {subject_type: user, predicate: friend, value_json: {name: susan}, confirmation_status: explicitly_stated}
  - checkpoint: after
    expected_active:
      - {key: user.friend, value: {name: Susan}}
      - {key: user.friend, value: {name: Michael}}
    expected_counts: {user.friend: 2}
```

- [ ] **Step 6: Run tests + full benchmark**

Run: `python -m pytest tests/ -q && python -m benchmark.runner`
Expected: all pass; `A1: 13/13 scenarios passed. Hard gates: clean.` (existing 12 unchanged, new one green).

- [ ] **Step 7: Commit**

```bash
git add app/canonical/models.py app/canonical/engine.py benchmark/scenarios/13_unknown_predicate_no_supersede.yaml tests/test_canonical_engine.py
git commit -m "feat(canonical): unknown cardinality accumulates, never supersedes (scenario 13)"
```

---

### Task 3: Extraction → Candidate mapper

**Files:**
- Create: `app/canonical/mapper.py`
- Test: `tests/test_mapper.py`

**Interfaces:**
- Consumes: `registry.canonical_predicate` (Task 1), `models.Candidate`, `models.CONFIRMATION_STATUSES` (Task 2).
- Produces: `map_canonical(obj: dict, sensitivity: str = "none", now: date | None = None) -> Candidate | None` — returns `None` for a missing/invalid/partial `canonical` object (an "unmapped" fact).

- [ ] **Step 1: Write the failing test**

Create `tests/test_mapper.py`:

```python
from datetime import date
from app.canonical.mapper import map_canonical


def test_maps_full_canonical_object():
    obj = {"subject_type": "user", "subject_id": "self", "predicate": "home_city",
           "value_json": {"city": "Easton", "state": "Pennsylvania"},
           "confirmation_status": "explicitly_stated",
           "observed_at": "2026-07-14", "valid_from": "2026-06-01"}
    c = map_canonical(obj, sensitivity="location", now=date(2026, 7, 14))
    assert c is not None
    assert c.predicate == "home_city"
    assert c.value_json == {"city": "Easton", "state": "Pennsylvania"}
    assert c.observed_at == date(2026, 7, 14)
    assert c.valid_from == date(2026, 6, 1)
    assert c.sensitivity == "location"


def test_alias_predicate_is_canonicalized():
    c = map_canonical({"predicate": "lives_in", "value_json": {"city": "Reading"}})
    assert c.predicate == "home_city"


def test_missing_predicate_or_value_returns_none():
    assert map_canonical({"value_json": {"city": "X"}}) is None
    assert map_canonical({"predicate": "home_city"}) is None
    assert map_canonical({"predicate": "home_city", "value_json": {}}) is None
    assert map_canonical(None) is None
    assert map_canonical("not a dict") is None


def test_defaults_and_invalid_confirmation():
    c = map_canonical({"predicate": "friend", "value_json": {"name": "Sue"},
                       "confirmation_status": "totally_made_up"})
    assert c.subject_type == "user"
    assert c.subject_id == "self"
    assert c.scope == "global"
    assert c.confirmation_status == "inferred"  # invalid value falls back


def test_bad_dates_are_dropped_not_fatal():
    c = map_canonical({"predicate": "home_city", "value_json": {"city": "X"},
                       "valid_from": "not-a-date"})
    assert c is not None
    assert c.valid_from is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mapper.py -q`
Expected: FAIL (`No module named 'app.canonical.mapper'`).

- [ ] **Step 3: Write `app/canonical/mapper.py`**

```python
"""Map a nested `canonical` extraction object to an engine Candidate.

The extraction LLM emits, per fact, a `canonical` sub-object alongside the
legacy category/fact/sensitivity fields. This mapper is the ONLY place that
turns that raw object into a Candidate; a missing/invalid/partial object
yields None (the fact is 'unmapped' and only the legacy path stores it).
"""
from __future__ import annotations

from datetime import date

from app.canonical import registry
from app.canonical.models import Candidate, CONFIRMATION_STATUSES


def _parse_date(v) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def map_canonical(obj, sensitivity: str = "none", now: date | None = None) -> Candidate | None:
    if not isinstance(obj, dict):
        return None
    predicate = obj.get("predicate")
    value_json = obj.get("value_json")
    if not isinstance(predicate, str) or not predicate.strip():
        return None
    if not isinstance(value_json, dict) or not value_json:
        return None

    conf = obj.get("confirmation_status") or "inferred"
    if conf not in CONFIRMATION_STATUSES:
        conf = "inferred"

    return Candidate(
        subject_type=(obj.get("subject_type") or "user"),
        subject_id=(obj.get("subject_id") or "self"),
        predicate=registry.canonical_predicate(predicate),
        value_json=value_json,
        scope=(obj.get("scope") or "global"),
        companion_id=obj.get("companion_id"),
        valid_from=_parse_date(obj.get("valid_from")),
        valid_until=_parse_date(obj.get("valid_until")),
        observed_at=_parse_date(obj.get("observed_at")) or now,
        confirmation_status=conf,
        sensitivity=sensitivity,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_mapper.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/canonical/mapper.py tests/test_mapper.py
git commit -m "feat(canonical): map nested canonical extraction object to Candidate"
```

---

### Task 4: Delta computation (before/after → persistable delta + events)

**Files:**
- Create: `app/canonical/delta.py`
- Test: `tests/test_delta.py`

**Interfaces:**
- Consumes: `models.Fact`; the output of `apply_candidate` (the `after` list) vs. the loaded `before` list.
- Produces: `Delta(inserts: list[Fact], supersedes: list[dict], events: list[dict], is_empty())` and `compute_delta(before, after, *, engine_version, candidate_id=None) -> Delta`. `supersedes` entries are `{"id", "expected_version", "new_status", "valid_until"}` for the CAS RPC (Stage 2).

- [ ] **Step 1: Write the failing test**

Create `tests/test_delta.py`:

```python
from datetime import date
from app.canonical.engine import apply_candidate
from app.canonical.delta import compute_delta
from app.canonical.models import Candidate, Fact


def _home(city, conf="explicitly_stated", vf=None):
    return Candidate(subject_type="user", predicate="home_city",
                     value_json={"city": city}, confirmation_status=conf, valid_from=vf)


def _active_home(city, version=1):
    from app.canonical.engine import normalize_value
    return Fact(id=f"id-{city}", subject_type="user", subject_id="user",
                predicate="home_city", value_json={"city": city},
                normalized_value=normalize_value({"city": city}), version=version,
                cardinality="single")


def test_insert_only_when_no_prior():
    now = date(2027, 1, 1)
    before = []
    after = apply_candidate(before, _home("Easton"), now)
    d = compute_delta(before, after, engine_version="v1")
    assert len(d.inserts) == 1 and not d.supersedes
    assert any(e["event_type"] == "fact_created" for e in d.events)


def test_supersession_produces_insert_plus_conditional_supersede():
    now = date(2027, 2, 1)
    before = [_active_home("Bethlehem", version=3)]
    after = apply_candidate(before, _home("Easton"), now)
    d = compute_delta(before, after, engine_version="v1")
    assert len(d.inserts) == 1
    assert len(d.supersedes) == 1
    op = d.supersedes[0]
    assert op["id"] == "id-Bethlehem"
    assert op["expected_version"] == 3
    assert op["new_status"] == "superseded"
    kinds = {e["event_type"] for e in d.events}
    assert "fact_superseded" in kinds and "fact_created" in kinds


def test_dedup_is_empty_delta():
    now = date(2027, 1, 1)
    before = [_active_home("Easton")]
    after = apply_candidate(before, _home("Easton"), now)
    d = compute_delta(before, after, engine_version="v1")
    assert d.is_empty()
    assert [e["event_type"] for e in d.events] == ["fact_deduped"]
```

Note: `Fact` needs a `version` field for the CAS delta. It is not on the merged model yet — add `version: int = 1` to `Fact` in `app/canonical/models.py` as part of this task (Step 3a) before writing `delta.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_delta.py -q`
Expected: FAIL (`No module named 'app.canonical.delta'`; `Fact` has no `version`).

- [ ] **Step 3a: Add `version` to `Fact`**

In `app/canonical/models.py`, add to `Fact` (after `observed_at`):

```python
    version: int = 1
```

- [ ] **Step 3b: Write `app/canonical/delta.py`**

```python
"""Diff the engine's before/after fact lists into a persistable, race-safe delta.

The engine is pure and returns a NEW `after` list. This module turns
(before, after) into:
  - inserts: brand-new Fact rows (active or historical-superseded)
  - supersedes: conditional status changes on EXISTING rows, carrying the
    expected version for optimistic compare-and-swap (applied by the Stage-2 RPC)
  - events: an audit trail for canonical_fact_events (restrained payloads)
No truth logic lives here — it only observes what the engine decided.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.canonical.models import Fact


@dataclass
class Delta:
    inserts: list[Fact] = field(default_factory=list)
    supersedes: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.inserts and not self.supersedes


def _event(event_type, fact, *, engine_version, candidate_id, related_fact_id=None):
    return {
        "event_type": event_type,
        "fact_id": fact.id,
        "related_fact_id": related_fact_id,
        "predicate": fact.predicate,
        "engine_version": engine_version,
        "candidate_id": candidate_id,
        "payload": {
            "normalized_value": fact.normalized_value,
            "status": fact.status,
        },
    }


def compute_delta(before, after, *, engine_version: str, candidate_id: str | None = None) -> Delta:
    before_by_id = {f.id: f for f in before}
    after_ids = {f.id for f in after}
    delta = Delta()

    # New rows (ids not present in `before`).
    for f in after:
        if f.id in before_by_id:
            continue
        delta.inserts.append(f)
        if f.status == "active":
            delta.events.append(_event("fact_created", f, engine_version=engine_version,
                                       candidate_id=candidate_id,
                                       related_fact_id=f.supersedes_fact_id))
        else:  # historical value recorded as already-superseded
            delta.events.append(_event("candidate_unconfirmed", f, engine_version=engine_version,
                                       candidate_id=candidate_id))

    # Existing rows whose status changed (active -> superseded/deleted).
    for f in after:
        prev = before_by_id.get(f.id)
        if prev is None or prev.status == f.status:
            continue
        delta.supersedes.append({
            "id": f.id,
            "expected_version": prev.version,
            "new_status": f.status,
            "valid_until": f.valid_until,
        })
        etype = "fact_deleted" if f.status == "deleted" else "fact_superseded"
        delta.events.append(_event(etype, f, engine_version=engine_version,
                                   candidate_id=candidate_id))

    # Pure dedup / no-op: nothing new, nothing changed.
    if delta.is_empty() and len(after) == len(before) and after_ids == set(before_by_id):
        delta.events.append({"event_type": "fact_deduped", "engine_version": engine_version,
                             "candidate_id": candidate_id})

    return delta
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_delta.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/canonical/models.py app/canonical/delta.py tests/test_delta.py
git commit -m "feat(canonical): compute persistable delta + audit events from engine output"
```

---

### Task 5: Full-suite green gate

**Files:** none (verification + branch finish).

- [ ] **Step 1: Run the entire suite**

Run: `python -m pytest tests/ -q && python -m benchmark.runner`
Expected: all pass; `A1: 13/13 scenarios passed. Hard gates: clean.`

- [ ] **Step 2: Confirm no production code was touched**

Run: `git diff --name-only origin/main... | grep -vE '^artifacts/voice-companion/(app/canonical/|benchmark/|tests/|docs/)' || echo "CLEAN: only canonical/benchmark/tests/docs changed"`
Expected: `CLEAN: only canonical/benchmark/tests/docs changed` (no router/extractor/schema changes in this plan).

- [ ] **Step 3: Finish the branch**

Announce and use **superpowers:finishing-a-development-branch** to verify tests, push, and open the PR (`feat/canonical-ledger-spine` → `main`), reporting the proven `pytest` + `13/13` result.

---

## Roadmap — remaining shadow-mode plans (not this plan)

2. **Schema & delta-RPC** — `migrations/0002_canonical_ledger_shadow.sql`: the four tables (`canonical_facts`, `canonical_fact_events`, `ledger_shadow_divergences`, `ledger_shadow_runs`), the three per-cardinality partial unique indexes, supporting/idempotency indexes, and the transactional `apply_canonical_delta` RPC (commits delta + events atomically under snapshot-match CAS).
3. **Live wiring** — nested-`canonical` prompt behind the A/B corpus gate; `extract_and_save_core_facts` → `LegacyOutcome` refactor; per-turn `exchange_id` minting + threading (and `id` on archived messages); always-run `shadow_ledger.run` with timeout + `should_collect` gating; `repository.py` load/persist with retry-on-conflict.
4. **Observability** — `ledger_shadow_runs` receipts, divergence recording + classifier, daily rollup + 0.5–1% agreement sample, read-only admin endpoint (real admin authz).
5. **Privacy & lifecycle** — retention job (30–90d on detailed values), `delete_account` extension to all four tables, sensitive-payload metadata-only enforcement.
