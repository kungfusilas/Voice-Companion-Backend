# Memory Benchmark — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic foundation of the long-term-memory benchmark — a gold-timeline format, a pure `canonical_facts` engine (with a predicate-cardinality registry), and a runner with Layer-A1 lifecycle scenarios + Layer-E hard gates.

**Architecture:** Pure-Python, no DB, no LLM. The engine is a set of pure functions over an in-memory `list[Fact]`; the benchmark loads YAML gold timelines, feeds each event's recorded extraction candidate / control through the engine via an adapter, and asserts the canonical state at each checkpoint. Everything runs under pytest on every PR.

**Tech Stack:** Python 3.11+, `dataclasses`, `pyyaml`, `pytest`.

## Global Constraints

- No LLM and no live database anywhere in Phase 1 — pure logic over YAML fixtures (deterministic).
- Sensitivity tag set (verbatim): `health, mental-health, location, financial, sexual, family, religion-beliefs, political-views, none`.
- Fact `status` values: `active | superseded | deleted | expired | unconfirmed`.
- `confirmation_status` values: `inferred | explicitly_stated | user_confirmed | user_corrected | disputed`.
- Scope values: `global | companion | session | vault`.
- Governing rule: the engine decides truth — a `user_confirmed`/`user_corrected` fact outranks a conflicting `inferred` candidate.
- Dates are `datetime.date`; comparisons use `valid_from`/`valid_until`, never apply-order.
- Privacy/isolation failures are **hard gates**: they fail the run, never averaged into a score.

## File Structure

- `artifacts/voice-companion/app/canonical/__init__.py` — package marker.
- `artifacts/voice-companion/app/canonical/models.py` — `Fact`, `Candidate`, `Control` dataclasses.
- `artifacts/voice-companion/app/canonical/registry.py` — predicate cardinality + sub_key derivation.
- `artifacts/voice-companion/app/canonical/engine.py` — `normalize_value`, `identity`, `apply_candidate`, `apply_control`, `active_facts`.
- `artifacts/voice-companion/benchmark/__init__.py`, `loader.py`, `adapter.py`, `runner.py`.
- `artifacts/voice-companion/benchmark/scenarios/*.yaml` — 12 gold timelines.
- `artifacts/voice-companion/tests/test_canonical_engine.py`, `test_benchmark_loader.py`, `test_benchmark_runner.py`, `test_scenarios.py`.
- `artifacts/voice-companion/requirements-dev.txt` — add `pyyaml`.

Run all tests: `cd artifacts/voice-companion && python -m pytest tests/ -q`

---

### Task 1: Models + predicate registry + normalize/identity

**Files:**
- Create: `app/canonical/__init__.py` (empty), `app/canonical/models.py`, `app/canonical/registry.py`, `app/canonical/engine.py`
- Test: `tests/test_canonical_engine.py`
- Modify: `requirements-dev.txt` (add `pyyaml`)

**Interfaces produced:**
- `Fact`, `Candidate`, `Control` dataclasses (fields below).
- `registry.cardinality(predicate) -> "single"|"multi"`, `registry.sub_key(predicate, value_json) -> str|None`.
- `engine.normalize_value(value_json: dict) -> str`, `engine.identity(subject_type, subject_id, predicate, scope, companion_id, value_json, registry) -> tuple`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_canonical_engine.py
from datetime import date
from app.canonical import engine, registry
from app.canonical.models import Fact, Candidate

def test_normalize_is_case_and_order_insensitive():
    assert engine.normalize_value({"city": "Easton"}) == engine.normalize_value({"city": "easton"})
    assert engine.normalize_value({"a": "x", "b": "y"}) == engine.normalize_value({"b": "y", "a": "x"})

def test_registry_cardinality():
    assert registry.cardinality("home_city") == "single"
    assert registry.cardinality("children") == "multi"
    assert registry.cardinality("unknown_predicate") == "single"  # safe default

def test_identity_single_ignores_value_multi_uses_subkey():
    single = engine.identity("user", "u1", "home_city", "global", None, {"city": "Easton"}, registry)
    single2 = engine.identity("user", "u1", "home_city", "global", None, {"city": "Erie"}, registry)
    assert single == single2  # same identity regardless of value (single-valued)
    kid_a = engine.identity("user", "u1", "children", "global", None, {"name": "Emmie"}, registry)
    kid_b = engine.identity("user", "u1", "children", "global", None, {"name": "Sam"}, registry)
    assert kid_a != kid_b  # distinct sub_keys → distinct identity
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_canonical_engine.py -q`
Expected: FAIL — `ModuleNotFoundError: app.canonical`.

- [ ] **Step 3: Implement models, registry, and the two helpers**

`app/canonical/models.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date

@dataclass
class Fact:
    id: str
    subject_type: str
    subject_id: str
    predicate: str
    value_json: dict
    normalized_value: str
    status: str = "active"          # active|superseded|deleted|expired|unconfirmed
    scope: str = "global"           # global|companion|session|vault
    companion_id: str | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    supersedes_fact_id: str | None = None
    confirmation_status: str = "inferred"
    sensitivity: str = "none"
    sub_key: str | None = None

@dataclass
class Candidate:
    subject_type: str
    predicate: str
    value_json: dict
    subject_id: str = "user"
    scope: str = "global"
    companion_id: str | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    confirmation_status: str = "inferred"
    sensitivity: str = "none"

@dataclass
class Control:
    op: str                          # forget|confirm|never_remember
    key: str                         # "<subject_type>.<predicate>" shorthand
    subject_id: str = "user"
    scope: str = "global"
    companion_id: str | None = None
```

`app/canonical/registry.py`:
```python
"""Predicate cardinality + sub_key derivation. Extend as new predicates appear."""

# Multi-valued predicates accumulate; each entry keyed by a field of value_json.
_MULTI: dict[str, str] = {
    "children": "name",
    "pets": "name",
    "hobbies": "name",
}

def cardinality(predicate: str) -> str:
    return "multi" if predicate in _MULTI else "single"  # single is the safe default

def sub_key(predicate: str, value_json: dict) -> str | None:
    field = _MULTI.get(predicate)
    if field is None:
        return None
    return str(value_json.get(field, "")).strip().lower()
```

`app/canonical/engine.py` (helpers only for now):
```python
from __future__ import annotations
import json
from datetime import date
from app.canonical.models import Fact, Candidate, Control
from app.canonical import registry

def normalize_value(value_json: dict) -> str:
    """Deterministic, case-insensitive canonical string for comparison."""
    def norm(v):
        if isinstance(v, str):
            return v.strip().lower()
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items()}
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v
    return json.dumps(norm(value_json), sort_keys=True, ensure_ascii=False)

def identity(subject_type, subject_id, predicate, scope, companion_id, value_json, reg=registry) -> tuple:
    """Identity for supersession/dedup. Single-valued ignores value; multi uses sub_key."""
    sk = reg.sub_key(predicate, value_json) if reg.cardinality(predicate) == "multi" else None
    return (subject_type, subject_id, predicate, scope, companion_id, sk)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_canonical_engine.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add artifacts/voice-companion/app/canonical/ artifacts/voice-companion/tests/test_canonical_engine.py artifacts/voice-companion/requirements-dev.txt
git commit -m "feat(canonical): models, predicate registry, normalize/identity helpers"
```

---

### Task 2: `apply_candidate` — single-valued lifecycle

**Files:** Modify `app/canonical/engine.py`; add tests to `tests/test_canonical_engine.py`.

**Interfaces produced:** `engine.apply_candidate(facts: list[Fact], cand: Candidate, now: date, reg=registry) -> list[Fact]` — returns a NEW list; never mutates input.

- [ ] **Step 1: Write failing tests**

```python
def _cand(**kw):
    base = dict(subject_type="user", predicate="home_city", value_json={"city": "Bethlehem"},
                confirmation_status="explicitly_stated", valid_from=date(2026,1,10))
    base.update(kw); return Candidate(**base)

def _active(facts):
    return [f for f in facts if f.status == "active"]

def test_upsert_new_fact():
    facts = engine.apply_candidate([], _cand(), now=date(2026,1,10))
    assert len(_active(facts)) == 1
    assert _active(facts)[0].value_json == {"city": "Bethlehem"}

def test_dedup_identical_mentions():
    facts = engine.apply_candidate([], _cand(), now=date(2026,1,10))
    facts = engine.apply_candidate(facts, _cand(), now=date(2026,1,11))
    assert len(_active(facts)) == 1  # ten identical → one

def test_idempotent_double_apply():
    facts = engine.apply_candidate([], _cand(), now=date(2026,1,10))
    n = len(facts)
    facts2 = engine.apply_candidate(facts, _cand(), now=date(2026,1,10))
    assert len(facts2) == n  # no growth, no doubled state

def test_supersession_new_value():
    facts = engine.apply_candidate([], _cand(), now=date(2026,1,10))
    facts = engine.apply_candidate(facts, _cand(value_json={"city": "Easton"},
                confirmation_status="user_corrected", valid_from=date(2027,3,15)), now=date(2027,4,15))
    act = _active(facts)
    assert len(act) == 1 and act[0].value_json == {"city": "Easton"}
    superseded = [f for f in facts if f.status == "superseded"]
    assert len(superseded) == 1 and superseded[0].value_json == {"city": "Bethlehem"}
    assert act[0].supersedes_fact_id == superseded[0].id

def test_confirmation_precedence_blocks_inferred_override():
    facts = engine.apply_candidate([], _cand(value_json={"city":"Easton"}, confirmation_status="user_confirmed"),
                now=date(2027,1,1))
    facts = engine.apply_candidate(facts, _cand(value_json={"city":"Reading"}, confirmation_status="inferred",
                valid_from=date(2027,2,1)), now=date(2027,2,1))
    act = _active(facts)
    assert len(act) == 1 and act[0].value_json == {"city": "Easton"}  # inferred did NOT override confirmed

def test_out_of_order_correction_keeps_current():
    # current fact valid_from 2027-03-15; a candidate with EARLIER valid_from is historical
    facts = engine.apply_candidate([], _cand(value_json={"city":"Easton"}, valid_from=date(2027,3,15)), now=date(2027,4,1))
    facts = engine.apply_candidate(facts, _cand(value_json={"city":"Bethlehem"}, valid_from=date(2026,1,10)), now=date(2027,4,2))
    act = _active(facts)
    assert len(act) == 1 and act[0].value_json == {"city": "Easton"}  # older-dated candidate does not become current
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_canonical_engine.py -k apply_candidate or supersession or dedup or upsert or idempotent or confirmation or out_of_order -q`
Expected: FAIL — `AttributeError: module 'engine' has no attribute 'apply_candidate'`.

- [ ] **Step 3: Implement `apply_candidate` (single-valued path)**

Append to `engine.py`:
```python
import uuid

_CONFIRM_RANK = {"disputed": 0, "inferred": 1, "explicitly_stated": 2, "user_confirmed": 3, "user_corrected": 3}

def _new_fact(cand: Candidate, now: date, status="active", supersedes=None, sub_key=None) -> Fact:
    return Fact(
        id=str(uuid.uuid4()), subject_type=cand.subject_type, subject_id=cand.subject_id,
        predicate=cand.predicate, value_json=cand.value_json, normalized_value=normalize_value(cand.value_json),
        status=status, scope=cand.scope, companion_id=cand.companion_id,
        valid_from=cand.valid_from or now, valid_until=cand.valid_until,
        supersedes_fact_id=supersedes, confirmation_status=cand.confirmation_status,
        sensitivity=cand.sensitivity, sub_key=sub_key,
    )

def apply_candidate(facts, cand: Candidate, now: date, reg=registry):
    facts = list(facts)
    ident = identity(cand.subject_type, cand.subject_id, cand.predicate, cand.scope,
                     cand.companion_id, cand.value_json, reg)
    sk = ident[-1]
    norm = normalize_value(cand.value_json)
    # existing ACTIVE fact(s) sharing this identity
    peers = [f for f in facts if f.status == "active" and identity(
        f.subject_type, f.subject_id, f.predicate, f.scope, f.companion_id, f.value_json, reg) == ident]
    if not peers:
        facts.append(_new_fact(cand, now, sub_key=sk))
        return facts
    cur = peers[0]
    if cur.normalized_value == norm:
        return facts  # dedup / idempotent — same value, same identity
    # different value → supersede, subject to confirmation precedence + temporal order
    cand_from = cand.valid_from or now
    if _CONFIRM_RANK[cand.confirmation_status] < _CONFIRM_RANK[cur.confirmation_status]:
        return facts  # lower-authority candidate cannot override a higher-authority current fact
    if cur.valid_from and cand_from < cur.valid_from:
        # candidate is historical (older effective date) → record as superseded, don't replace current
        facts.append(_new_fact(cand, now, status="superseded"))
        return facts
    idx = facts.index(cur)
    facts[idx] = Fact(**{**cur.__dict__, "status": "superseded", "valid_until": cand_from})
    facts.append(_new_fact(cand, now, supersedes=cur.id, sub_key=sk))
    return facts
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_canonical_engine.py -q`
Expected: all passing (Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add artifacts/voice-companion/app/canonical/engine.py artifacts/voice-companion/tests/test_canonical_engine.py
git commit -m "feat(canonical): apply_candidate single-valued (upsert/dedup/supersede/precedence/temporal)"
```

---

### Task 3: `apply_candidate` — multi-valued lifecycle

**Files:** tests in `tests/test_canonical_engine.py` (no engine change expected — verifies the multi path works).

**Interfaces:** Consumes `engine.apply_candidate`, `registry.sub_key`.

- [ ] **Step 1: Write failing tests**

```python
def _kid(name, city="x", **kw):
    return Candidate(subject_type="user", predicate="children", value_json={"name": name},
                     confirmation_status="explicitly_stated", valid_from=date(2026,1,1), **kw)

def test_multi_accumulates_distinct():
    facts = engine.apply_candidate([], _kid("Emmie"), now=date(2026,1,1))
    facts = engine.apply_candidate(facts, _kid("Sam"), now=date(2026,1,2))
    act = [f for f in facts if f.status == "active"]
    assert {f.value_json["name"] for f in act} == {"Emmie", "Sam"}  # both, neither superseded
    assert not [f for f in facts if f.status == "superseded"]

def test_multi_dedup_same_subkey():
    facts = engine.apply_candidate([], _kid("Emmie"), now=date(2026,1,1))
    facts = engine.apply_candidate(facts, _kid("emmie"), now=date(2026,1,2))  # case-insensitive sub_key
    assert len([f for f in facts if f.status == "active"]) == 1
```

- [ ] **Step 2: Run to verify** — Run the two tests; they should PASS already if Task 2's identity/sub_key logic is correct. If `test_multi_dedup_same_subkey` fails, ensure `registry.sub_key` lowercases (it does) and identity uses it.

- [ ] **Step 3:** No new implementation expected. If a test fails, the fix is in `registry.sub_key`/`identity` — align them so multi-valued identity keys on the lowercased sub_key.

- [ ] **Step 4: Run** `python -m pytest tests/test_canonical_engine.py -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add artifacts/voice-companion/tests/test_canonical_engine.py
git commit -m "test(canonical): multi-valued accumulation + dedup coverage"
```

---

### Task 4: `apply_control` — forget / confirm / never_remember

**Files:** Modify `app/canonical/engine.py`; tests in `tests/test_canonical_engine.py`.

**Interfaces produced:** `engine.apply_control(facts, ctrl: Control, now: date, prohibited: set|None=None) -> tuple[list[Fact], set]` — returns `(facts, prohibited_keys)`. `apply_candidate` gains a `prohibited: set` param that refuses matching candidates.

- [ ] **Step 1: Write failing tests**

```python
from app.canonical.models import Control

def test_forget_deletes_active():
    facts = engine.apply_candidate([], _cand(), now=date(2026,1,10))
    facts, _ = engine.apply_control(facts, Control(op="forget", key="user.home_city"), now=date(2026,2,1))
    assert not [f for f in facts if f.status == "active"]
    assert [f for f in facts if f.status == "deleted"]

def test_confirm_upgrades_status():
    facts = engine.apply_candidate([], _cand(confirmation_status="inferred"), now=date(2026,1,10))
    facts, _ = engine.apply_control(facts, Control(op="confirm", key="user.home_city"), now=date(2026,2,1))
    assert [f for f in facts if f.status=="active"][0].confirmation_status == "user_confirmed"

def test_never_remember_blocks_future_candidate():
    facts, prohibited = engine.apply_control([], Control(op="never_remember", key="user.home_city"), now=date(2026,1,1))
    facts = engine.apply_candidate(facts, _cand(), now=date(2026,1,10), prohibited=prohibited)
    assert not [f for f in facts if f.status == "active"]  # candidate refused
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_canonical_engine.py -k control or forget or confirm or never_remember -q` → FAIL (`apply_control` missing).

- [ ] **Step 3: Implement**

Add to `engine.py`; also add the `prohibited` param to `apply_candidate` (near the top, after computing `ident`):
```python
def _key_of(f_or_ctrl) -> str:
    return f"{f_or_ctrl.subject_type}.{f_or_ctrl.predicate}"

def apply_control(facts, ctrl: Control, now: date, prohibited=None):
    facts = list(facts); prohibited = set(prohibited or set())
    if ctrl.op == "never_remember":
        prohibited.add(ctrl.key)
        return facts, prohibited
    for i, f in enumerate(facts):
        if f.status != "active" or _key_of(f) != ctrl.key:
            continue
        if ctrl.op == "forget":
            facts[i] = Fact(**{**f.__dict__, "status": "deleted", "valid_until": now})
        elif ctrl.op == "confirm":
            facts[i] = Fact(**{**f.__dict__, "confirmation_status": "user_confirmed"})
    return facts, prohibited
```
In `apply_candidate`, change the signature to `apply_candidate(facts, cand, now, reg=registry, prohibited=None)` and add, right after `facts = list(facts)`:
```python
    if prohibited and f"{cand.subject_type}.{cand.predicate}" in prohibited:
        return facts  # user prohibited this key from ever being stored
```

- [ ] **Step 4: Run** `python -m pytest tests/test_canonical_engine.py -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add artifacts/voice-companion/app/canonical/engine.py artifacts/voice-companion/tests/test_canonical_engine.py
git commit -m "feat(canonical): apply_control (forget/confirm/never_remember) + prohibition gate"
```

---

### Task 5: `active_facts` — scope isolation, expiry, windowing

**Files:** Modify `app/canonical/engine.py`; tests in `tests/test_canonical_engine.py`.

**Interfaces produced:** `engine.active_facts(facts, at_time: date, scope="global", companion_id=None) -> list[Fact]`.

- [ ] **Step 1: Write failing tests**

```python
def test_active_facts_scope_isolation():
    aeva = engine.apply_candidate([], _cand(scope="companion", companion_id="aeva"), now=date(2026,1,10))
    # visible to aeva
    assert len(engine.active_facts(aeva, date(2026,2,1), scope="companion", companion_id="aeva")) == 1
    # NOT visible to aria
    assert len(engine.active_facts(aeva, date(2026,2,1), scope="companion", companion_id="aria")) == 0

def test_global_visible_to_any_companion():
    g = engine.apply_candidate([], _cand(scope="global"), now=date(2026,1,10))
    assert len(engine.active_facts(g, date(2026,2,1), scope="companion", companion_id="aria")) == 1

def test_expiry_excludes_past_valid_until():
    facts = engine.apply_candidate([], _cand(valid_from=date(2026,1,1), valid_until=date(2026,2,1)), now=date(2026,1,1))
    assert len(engine.active_facts(facts, date(2026,1,15))) == 1   # within window
    assert len(engine.active_facts(facts, date(2026,3,1))) == 0    # expired

def test_not_yet_valid_excluded():
    facts = engine.apply_candidate([], _cand(valid_from=date(2027,1,1)), now=date(2027,1,1))
    assert len(engine.active_facts(facts, date(2026,6,1))) == 0    # before valid_from
```

- [ ] **Step 2: Run to verify failure** — FAIL (`active_facts` missing).

- [ ] **Step 3: Implement**

```python
def active_facts(facts, at_time: date, scope="global", companion_id=None):
    out = []
    for f in facts:
        if f.status != "active":
            continue
        if f.valid_from and f.valid_from > at_time:
            continue
        if f.valid_until and f.valid_until <= at_time:
            continue
        # scope visibility: global facts always visible; companion facts only to that companion
        if f.scope == "global":
            out.append(f)
        elif f.scope == "companion" and scope == "companion" and f.companion_id == companion_id:
            out.append(f)
    return out
```

- [ ] **Step 4: Run** `python -m pytest tests/test_canonical_engine.py -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add artifacts/voice-companion/app/canonical/engine.py artifacts/voice-companion/tests/test_canonical_engine.py
git commit -m "feat(canonical): active_facts with scope isolation + temporal windowing"
```

---

### Task 6: Gold-timeline loader + validation

**Files:** Create `benchmark/__init__.py` (empty), `benchmark/loader.py`; Test `tests/test_benchmark_loader.py`.

**Interfaces produced:** `loader.load_scenario(path) -> Scenario` where `Scenario` has `.name`, `.events` (list of dicts with parsed `date`, and `Candidate`/`Control` objects), `.checkpoints`. Raises `ValueError` on schema violations.

- [ ] **Step 1: Write failing test**

```python
# tests/test_benchmark_loader.py
import textwrap, pathlib
from benchmark import loader

def test_loads_events_and_checkpoints(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(textwrap.dedent('''
      scenario: t
      events:
        - time: "2026-01-10"
          companion: aeva
          user: "I live in Bethlehem."
          extraction:
            - subject_type: user
              predicate: home_city
              value_json: {city: Bethlehem}
              confirmation_status: explicitly_stated
              valid_from: "2026-01-10"
        - checkpoint: c1
          expected_active:
            - key: user.home_city
              value: {city: Bethlehem}
    '''))
    sc = loader.load_scenario(str(p))
    assert sc.name == "t"
    assert len(sc.events) == 2

def test_rejects_bad_status(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text('scenario: b\nevents:\n  - checkpoint: c\n    expected_active:\n      - key: 123\n')
    import pytest
    with pytest.raises(ValueError):
        loader.load_scenario(str(p))
```

- [ ] **Step 2: Run to verify failure** — FAIL (`benchmark.loader` missing).

- [ ] **Step 3: Implement `benchmark/loader.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
import yaml
from app.canonical.models import Candidate, Control

def _to_date(s): return date.fromisoformat(str(s))

@dataclass
class Scenario:
    name: str
    events: list = field(default_factory=list)  # each: {"kind","time",...}

def _parse_candidate(d: dict) -> Candidate:
    return Candidate(
        subject_type=d["subject_type"], predicate=d["predicate"], value_json=d["value_json"],
        subject_id=d.get("subject_id", "user"), scope=d.get("scope", "global"),
        companion_id=d.get("companion_id"),
        valid_from=_to_date(d["valid_from"]) if d.get("valid_from") else None,
        valid_until=_to_date(d["valid_until"]) if d.get("valid_until") else None,
        confirmation_status=d.get("confirmation_status", "inferred"),
        sensitivity=d.get("sensitivity", "none"),
    )

def load_scenario(path: str) -> Scenario:
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    if not raw or "scenario" not in raw:
        raise ValueError(f"{path}: missing 'scenario'")
    events = []
    for ev in raw.get("events", []):
        if "checkpoint" in ev:
            for a in ev.get("expected_active", []) + ev.get("expected_superseded", []) + ev.get("expected_absent", []):
                if not isinstance(a.get("key"), str):
                    raise ValueError(f"{path}: assertion 'key' must be a string, got {a.get('key')!r}")
            events.append({"kind": "checkpoint", "name": ev["checkpoint"], **ev})
        elif "control" in ev:
            c = ev["control"]
            events.append({"kind": "control", "time": _to_date(ev["time"]) if ev.get("time") else None,
                           "control": Control(op=c["op"], key=c["key"], subject_id=c.get("subject_id","user"),
                                              scope=c.get("scope","global"), companion_id=c.get("companion_id"))})
        else:
            events.append({"kind": "turn", "time": _to_date(ev["time"]),
                           "candidates": [_parse_candidate(x) for x in ev.get("extraction", [])]})
    return Scenario(name=raw["scenario"], events=events)
```

- [ ] **Step 4: Run** `python -m pytest tests/test_benchmark_loader.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add artifacts/voice-companion/benchmark/__init__.py artifacts/voice-companion/benchmark/loader.py artifacts/voice-companion/tests/test_benchmark_loader.py
git commit -m "feat(benchmark): gold-timeline loader + schema validation"
```

---

### Task 7: Adapter (engine seam)

**Files:** Create `benchmark/adapter.py`; Test `tests/test_benchmark_runner.py` (shared with Task 8).

**Interfaces produced:** `adapter.MemoryAdapter` with `apply_events(events) -> None` (runs turns/controls through the engine, tracking `now` + prohibited set) and `active_facts(at_time, scope="global", companion_id=None) -> list[Fact]`. Stubs: `retrieve`, `answer`, `rebuild` raise `NotImplementedError` (later slices).

- [ ] **Step 1: Write failing test**

```python
# tests/test_benchmark_runner.py
from datetime import date
from benchmark.adapter import MemoryAdapter
from app.canonical.models import Candidate, Control

def test_adapter_applies_turns_and_controls():
    a = MemoryAdapter()
    a.apply_events([
        {"kind": "turn", "time": date(2026,1,10),
         "candidates": [Candidate("user","home_city",{"city":"Bethlehem"}, valid_from=date(2026,1,10),
                                  confirmation_status="explicitly_stated")]},
        {"kind": "control", "time": date(2026,2,1), "control": Control(op="forget", key="user.home_city")},
    ])
    assert a.active_facts(date(2026,2,2)) == []
```

- [ ] **Step 2: Run to verify failure** — FAIL (`benchmark.adapter` missing).

- [ ] **Step 3: Implement `benchmark/adapter.py`**

```python
from __future__ import annotations
from datetime import date
from app.canonical import engine

class MemoryAdapter:
    def __init__(self):
        self.facts = []
        self.prohibited = set()

    def apply_events(self, events):
        for ev in events:
            if ev["kind"] == "turn":
                for cand in ev["candidates"]:
                    self.facts = engine.apply_candidate(self.facts, cand, now=ev["time"], prohibited=self.prohibited)
            elif ev["kind"] == "control":
                self.facts, self.prohibited = engine.apply_control(
                    self.facts, ev["control"], now=ev.get("time") or date.today(), prohibited=self.prohibited)

    def active_facts(self, at_time: date, scope="global", companion_id=None):
        return engine.active_facts(self.facts, at_time, scope=scope, companion_id=companion_id)

    def retrieve(self, query, k):  # Layer B slice
        raise NotImplementedError
    def answer(self, query):       # Layer C slice
        raise NotImplementedError
    def rebuild(self):             # Layer D slice
        raise NotImplementedError
```

- [ ] **Step 4: Run** `python -m pytest tests/test_benchmark_runner.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add artifacts/voice-companion/benchmark/adapter.py artifacts/voice-companion/tests/test_benchmark_runner.py
git commit -m "feat(benchmark): engine adapter (apply_events/active_facts + stubs)"
```

---

### Task 8: Runner + report + hard gates (E)

**Files:** Create `benchmark/runner.py`; tests in `tests/test_benchmark_runner.py`.

**Interfaces produced:** `runner.run_scenario(scenario) -> Result` where `Result` has `.name`, `.passed: bool`, `.assertion_failures: list[str]`, `.gate_failures: list[str]`. `runner.run_all(dir) -> list[Result]`. A checkpoint is evaluated by replaying events **up to** it and asserting `active_facts` at the checkpoint's implied time (the most recent event `time`, or `date.max` if none).

- [ ] **Step 1: Write failing tests**

```python
from benchmark import loader, runner

def test_runner_passes_good_scenario(tmp_path):
    p = tmp_path / "g.yaml"
    p.write_text('''
scenario: g
events:
  - time: "2026-01-10"
    companion: aeva
    user: "I live in Bethlehem."
    extraction:
      - {subject_type: user, predicate: home_city, value_json: {city: Bethlehem}, confirmation_status: explicitly_stated, valid_from: "2026-01-10"}
  - checkpoint: c1
    expected_active:
      - {key: user.home_city, value: {city: Bethlehem}}
''')
    res = runner.run_scenario(loader.load_scenario(str(p)))
    assert res.passed and not res.assertion_failures

def test_runner_fails_on_wrong_value(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text('''
scenario: b
events:
  - time: "2026-01-10"
    companion: aeva
    user: "x"
    extraction:
      - {subject_type: user, predicate: home_city, value_json: {city: Bethlehem}, confirmation_status: explicitly_stated, valid_from: "2026-01-10"}
  - checkpoint: c1
    expected_active:
      - {key: user.home_city, value: {city: Easton}}
''')
    res = runner.run_scenario(loader.load_scenario(str(p)))
    assert not res.passed and res.assertion_failures

def test_gate_fails_on_companion_leak(tmp_path):
    # companion-scoped fact must never appear in another companion's active set (checkpoint declares the check)
    p = tmp_path / "leak.yaml"
    p.write_text('''
scenario: leak
events:
  - time: "2026-01-10"
    companion: aeva
    user: "secret"
    extraction:
      - {subject_type: user, predicate: secret_note, value_json: {v: s}, scope: companion, companion_id: aeva, confirmation_status: explicitly_stated, valid_from: "2026-01-10"}
  - checkpoint: c1
    gate_no_leak_to: aria
    forbidden_keys: [user.secret_note]
''')
    res = runner.run_scenario(loader.load_scenario(str(p)))
    assert res.passed and not res.gate_failures  # engine correctly isolates → gate holds
```

- [ ] **Step 2: Run to verify failure** — FAIL (`benchmark.runner` missing). (Loader must also pass through `gate_no_leak_to`/`forbidden_keys`/`value` on checkpoint assertions — they already flow via `**ev` and the assertion dicts; `value` on an assertion is a dict and `key` is a string, so validation passes.)

- [ ] **Step 3: Implement `benchmark/runner.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from benchmark.adapter import MemoryAdapter
from benchmark import loader as _loader
from app.canonical.engine import normalize_value

@dataclass
class Result:
    name: str
    passed: bool = True
    assertion_failures: list = field(default_factory=list)
    gate_failures: list = field(default_factory=list)

def _key(f): return f"{f.subject_type}.{f.predicate}"

def run_scenario(scenario) -> Result:
    res = Result(name=scenario.name)
    adapter = MemoryAdapter()
    last_time = date.min
    applied = []
    for ev in scenario.events:
        if ev["kind"] in ("turn", "control"):
            adapter.apply_events([ev]); applied.append(ev)
            if ev.get("time"): last_time = ev["time"]
            continue
        # checkpoint: assert against current state at last_time
        at = last_time if last_time != date.min else date.max
        active = adapter.active_facts(at)
        active_by_key = {}
        for f in active:
            active_by_key.setdefault(_key(f), []).append(f)
        for exp in ev.get("expected_active", []):
            got = active_by_key.get(exp["key"], [])
            if not any(normalize_value(f.value_json) == normalize_value(exp["value"]) for f in got):
                res.assertion_failures.append(f"[{ev['name']}] expected active {exp['key']}={exp['value']}, got {[f.value_json for f in got]}")
        for exp in ev.get("expected_absent", []):
            if active_by_key.get(exp["key"]):
                res.assertion_failures.append(f"[{ev['name']}] expected absent {exp['key']}, but present")
        for exp in ev.get("expected_superseded", []):
            supers = [f for f in adapter.facts if _key(f)==exp["key"] and f.status=="superseded"
                      and normalize_value(f.value_json)==normalize_value(exp["value"])]
            if not supers:
                res.assertion_failures.append(f"[{ev['name']}] expected superseded {exp['key']}={exp['value']}, not found")
        # HARD GATE: forbidden keys must not appear in another companion's active set
        other = ev.get("gate_no_leak_to")
        if other:
            leaked = adapter.active_facts(at, scope="companion", companion_id=other)
            for f in leaked:
                if _key(f) in ev.get("forbidden_keys", []):
                    res.gate_failures.append(f"[{ev['name']}] LEAK: {_key(f)} visible to companion '{other}'")
    res.passed = not res.assertion_failures and not res.gate_failures
    return res

def run_all(scenario_dir: str) -> list:
    import glob
    return [run_scenario(_loader.load_scenario(p)) for p in sorted(glob.glob(f"{scenario_dir}/*.yaml"))]

if __name__ == "__main__":  # `python -m benchmark.runner`
    import os, json, sys, datetime
    d = os.path.join(os.path.dirname(__file__), "scenarios")
    results = run_all(d)
    gate_fail = any(r.gate_failures for r in results)
    passed = sum(1 for r in results if r.passed)
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"[{mark}] {r.name}")
        for m in r.assertion_failures + r.gate_failures:
            print(f"    {m}")
    print(f"\nA1: {passed}/{len(results)} scenarios passed. Hard gates: {'FAILED' if gate_fail else 'clean'}.")
    os.makedirs(os.path.join(d, "..", "results"), exist_ok=True)
    out = os.path.join(d, "..", "results", datetime.datetime.now().strftime("%Y%m%dT%H%M%S")+".json")
    json.dump({"passed": passed, "total": len(results), "gate_failed": gate_fail,
               "results": [r.__dict__ for r in results]}, open(out, "w"), indent=2, default=str)
    sys.exit(1 if (gate_fail or passed != len(results)) else 0)
```

- [ ] **Step 4: Run** `python -m pytest tests/test_benchmark_runner.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add artifacts/voice-companion/benchmark/runner.py artifacts/voice-companion/tests/test_benchmark_runner.py
git commit -m "feat(benchmark): scenario runner + report + companion-leak hard gate"
```

---

### Task 9: The 12 A1 scenarios + green run

**Files:** Create `benchmark/scenarios/*.yaml` (12 files); Test `tests/test_scenarios.py`.

**Interfaces:** Consumes `loader`, `runner`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scenarios.py
import os
from benchmark import runner
DIR = os.path.join(os.path.dirname(__file__), "..", "benchmark", "scenarios")

def test_all_scenarios_pass():
    results = runner.run_all(DIR)
    assert len(results) >= 12, f"expected >=12 scenarios, found {len(results)}"
    failures = [(r.name, r.assertion_failures + r.gate_failures) for r in results if not r.passed]
    assert not failures, f"scenario failures: {failures}"
```

- [ ] **Step 2: Run to verify failure** — FAIL (no scenarios yet → `len(results) >= 12` fails).

- [ ] **Step 3: Author the 12 scenarios** in `benchmark/scenarios/`, one behavior each, matching spec §6:
  `01_upsert.yaml`, `02_supersede_single.yaml`, `03_accumulate_multi.yaml`, `04_dedup_single.yaml`,
  `05_dedup_multi.yaml`, `06_distinct_not_merged.yaml`, `07_forget.yaml`, `08_scope_isolation.yaml`,
  `09_idempotency.yaml`, `10_out_of_order_temporal.yaml`, `11_confirmation_precedence.yaml`, `12_expiry.yaml`.

Each uses the format from Task 6/8. Example `02_supersede_single.yaml`:
```yaml
scenario: supersede_single
events:
  - time: "2026-01-10"
    companion: aeva
    user: "I live in Bethlehem, Pennsylvania."
    extraction:
      - {subject_type: user, predicate: home_city, value_json: {city: Bethlehem}, confirmation_status: explicitly_stated, valid_from: "2026-01-10"}
  - time: "2027-04-15"
    companion: aeva
    user: "I moved to Easton."
    extraction:
      - {subject_type: user, predicate: home_city, value_json: {city: Easton}, confirmation_status: user_corrected, valid_from: "2027-03-15"}
  - checkpoint: after_move
    expected_active:
      - {key: user.home_city, value: {city: Easton}}
    expected_superseded:
      - {key: user.home_city, value: {city: Bethlehem}}
```
Author the other 11 analogously, each asserting the behavior its filename names (use `control: {op: forget|never_remember|confirm}` for 07 & the prohibition case; two companions for 08; duplicate events for 09; `gate_no_leak_to` on 08; `valid_until` in the past for 12). Keep each minimal — one behavior, 1–2 checkpoints.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests/ -q` and `python -m benchmark.runner`
Expected: all pytest green; runner prints `A1: 12/12 scenarios passed. Hard gates: clean.` and exits 0.

- [ ] **Step 5: Commit**

```bash
git add artifacts/voice-companion/benchmark/scenarios/ artifacts/voice-companion/tests/test_scenarios.py
git commit -m "feat(benchmark): 12 A1 lifecycle scenarios — full deterministic suite green"
```

---

## Self-Review

**Spec coverage:** gold-timeline format (T6) · adapter contract incl. stubbed retrieve/answer/rebuild (T7) · runner+report (T8) · Layer-E hard gate (T8, companion-leak; extend in later slices) · A1 all 12 behaviors — upsert(T2/§6.1), supersede-single(T2/§6.2), accumulate-multi(T3/§6.3), dedup-single(T2/§6.4), dedup-multi(T3/§6.5), distinct-not-merged(T3/§6.6), forget(T4/§6.7), scope-isolation(T5/§6.8), idempotency(T2/§6.9), out-of-order-temporal(T2/§6.10), confirmation-precedence(T2/§6.11), expiry(T5/§6.12) · `canonical_facts` model incl. predicate cardinality registry (T1) · pure/deterministic, PR-runnable (all tasks). Deferred layers (B/C/D/A2/scale/episodic) intentionally absent — adapter stubs + format fields reserve their seams. ✔ No gaps.

**Placeholder scan:** No TBD/TODO. Task 9 Step 3 names all 12 files + gives one full example + exact per-file instructions (control ops, two-companion, duplicate events, valid_until) — concrete, not "similar to". The one "no new implementation expected" (T3) is a genuine verification task with real tests.

**Type consistency:** `apply_candidate(facts, cand, now, reg=registry, prohibited=None)`, `apply_control(...) -> (facts, prohibited)`, `active_facts(facts, at_time, scope, companion_id)`, `normalize_value(dict)->str`, `identity(...)->tuple` used identically across T1–T8. `Fact`/`Candidate`/`Control` fields consistent between models (T1), loader (T6), adapter (T7), runner (T8). Checkpoint keys (`expected_active/superseded/absent`, `gate_no_leak_to`, `forbidden_keys`, `value`, `key`) consistent between loader validation (T6), runner (T8), and scenarios (T9). ✔
