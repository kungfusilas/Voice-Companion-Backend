# Canonical Ledger Shadow Mode — Plan 3b: Shadow plumbing (live wiring)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the ledger's shadow path into the live chat flow — a per-turn `exchange_id`, a `LegacyOutcome`-returning extractor, and an always-run, fail-open, gated `shadow_ledger.run` that calls `apply_candidate_durably` — such that it is **a strict no-op in production until 3c ships the nested-`canonical` prompt**, legacy extraction behavior is **provably unchanged**, and the shadow path can never delay, alter, or fail a user's turn.

**Architecture:** Stage 3b of the shadow-mode rollout. Builds on 3a's `repository.py`. The one live-behavioral change is control flow (the extractor returns an outcome instead of early-returning; `exchange_id` is minted; a shadow bg-task is scheduled) — the legacy `user_core_facts` write logic is untouched, and the shadow path finds no `canonical` object to map until 3c, so it does nothing in prod. This IS the first stage that requires a **Republish** to deploy (Stages 1/2/3a were inert library/schema code); it stays **ledger-empty** until 3c.

**Tech Stack:** Python async, the `_bg` durable background-task machinery (PR #5), pytest (local pg via 3a's harness + fakes).

## Global Constraints

- **Legacy path unchanged.** The `user_core_facts` write in `extract_and_save_core_facts` must produce byte-identical behavior (same LLM prompt in 3b, same validation, dedup, 50-cap, insert). The refactor only *adds* a return value and reshapes early-returns into outcome returns.
- **Shadow is invisible + fail-open.** `shadow_ledger.run` catches all exceptions and returns a summary; it never raises into the caller. In `chat.py` it runs inside a `_bg` task wrapped in `asyncio.wait_for(..., timeout)`; a shadow failure/timeout changes nothing the user sees.
- **No-op without `canonical`.** A fact dict lacking a `canonical` object produces no candidate → no ledger write. Since 3b does not change the prompt, production extraction emits no `canonical` object, so the shadow path is a no-op in prod. **Stronger claim, tested:** an absent / `null` / `{}` / malformed `canonical` causes **zero** executor (DB) calls.
- **Timeout-safe / at-most-once.** A timeout or cancellation before, during, or immediately after persistence yields either zero commits or exactly one logical application — never a duplicate fact version or duplicate state transition. This holds because (a) `apply_candidate_durably` reloads and **dedups** (a re-applied candidate whose value is already active is an empty delta / no-op) and (b) the Stage-2 **idempotency index** makes an insert with the same `(owner, source_exchange_id, predicate, scope, companion, normalized_value, extractor_version)` an `ON CONFLICT DO NOTHING`. The persistence layer therefore treats "already applied" as **success, not error**. The per-turn `exchange_id` is that stable key. Proven by a same-`exchange_id` replay test.
- **Honor 3a's pre-3b checklist:** resolve the `subject_id` default (Task 1); always pass non-null `source_exchange_id` + `extractor_version`; use `should_collect` gating before any shadow write.
- **All prior tests + benchmark stay green.** Run from `artifacts/voice-companion/` via `./venv/bin/python`.

---

## File Structure

- Modify `app/canonical/models.py` — `Candidate.subject_id` / `Control.subject_id` default `"user"` → `"self"`.
- Modify `tests/test_delta.py` — update the `_active_home` helper's hardcoded `subject_id="user"`.
- Modify `app/memory_extractor.py` — `LegacyOutcome` + `extract_and_save_core_facts` returns it (legacy write unchanged).
- Create `app/shadow_ledger.py` — `run(outcome, *, owner_user_id, exchange_id, executor, settings, now)`.
- Create `tests/test_shadow_ledger.py` — the hermetic core (gate/map/apply/fail-open/no-op), against local pg + fakes.
- Modify `app/routers/chat.py` — mint `exchange_id`; a `_extract_and_shadow` bg wrapper at both call sites.
- Modify `app/conversation_store.py` — add `id` (the `exchange_id`) onto archived message dicts.
- Create `tests/test_shadow_wiring.py` — the bg wrapper + exchange_id threading + conversation id (fakes).

---

### Task 1: Resolve the `subject_id` default (pre-3b MUST-FIX)

**Files:**
- Modify: `app/canonical/models.py`
- Modify: `tests/test_delta.py`

**Interfaces:**
- Produces: `Candidate.subject_id` and `Control.subject_id` default to `"self"` (aligning with the DB column default, the slot indexes, and `map_canonical`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_canonical_engine.py`:

```python
def test_candidate_subject_id_defaults_to_self():
    from app.canonical.models import Candidate
    c = Candidate(subject_type="user", predicate="home_city", value_json={"city": "X"})
    assert c.subject_id == "self"
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_canonical_engine.py::test_candidate_subject_id_defaults_to_self -q`
Expected: FAIL (`assert 'user' == 'self'`).

- [ ] **Step 3: Align the defaults**

In `app/canonical/models.py`, change `Candidate.subject_id: str = "user"` → `subject_id: str = "self"` and `Control.subject_id: str = "user"` → `subject_id: str = "self"`.

- [ ] **Step 4: Fix the one test helper that hardcodes the old default**

In `tests/test_delta.py`, in the `_active_home` helper, change `subject_id="user"` → `subject_id="self"` (so it matches the candidates built via the now-`"self"` default). Grep the test suite for any other `subject_id="user"` that pairs with a defaulted candidate and align it.

- [ ] **Step 5: Run the whole suite + benchmark**

Run: `./venv/bin/python -m pytest tests/ -q && ./venv/bin/python -m benchmark.runner`
Expected: all pass; benchmark `A1: 13/13 scenarios passed. Hard gates: clean.` (scenarios key on `subject_type.predicate`, so the `subject_id` value doesn't change their assertions; the value is just internally consistent now.)

- [ ] **Step 6: Commit**

```bash
git add app/canonical/models.py tests/test_delta.py tests/test_canonical_engine.py
git commit -m "fix(canonical): default Candidate/Control subject_id to 'self' (align DB + indexes)"
```

---

### Task 2: `LegacyOutcome` — extractor returns parsed facts (legacy write unchanged)

**Files:**
- Modify: `app/memory_extractor.py`
- Test: `tests/test_legacy_outcome.py`

**Interfaces:**
- Produces: `LegacyOutcome` dataclass (`status: str`, `facts: list[dict]`); `extract_and_save_core_facts(...) -> LegacyOutcome`. `status ∈ {"inserted","capped","duplicate","gated","empty","error"}`; `facts` = the validated, sensitivity-tagged facts (each dict keeps any `canonical` key the LLM emitted), returned **regardless** of whether the legacy write inserted, capped, or deduped.

- [ ] **Step 1: Write the failing test**

Create `tests/test_legacy_outcome.py`:

```python
import asyncio
import json
from app import memory_extractor
from app.memory_extractor import LegacyOutcome


def _fake_llm(monkeypatch, payload):
    async def fake_send(*a, **kw):
        return json.dumps(payload)
    monkeypatch.setattr(memory_extractor.claude, "send_message", fake_send)


def _fake_supabase(monkeypatch, existing=None):
    # Make the httpx Supabase round-trips no-ops that report no existing facts.
    import httpx

    class _Resp:
        status_code = 200
        def json(self):
            return existing or []

    class _Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, *a, **kw):
            return _Resp()
        async def post(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _Client())
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "key")


def test_returns_outcome_with_parsed_facts_including_canonical(monkeypatch):
    _fake_llm(monkeypatch, [
        {"category": "location", "fact": "Lives in Easton", "sensitivity": "none",
         "canonical": {"subject_type": "user", "predicate": "home_city",
                       "value_json": {"city": "Easton"}}}])
    _fake_supabase(monkeypatch)
    out = asyncio.run(memory_extractor.extract_and_save_core_facts("u1", "msg", "reply"))
    assert isinstance(out, LegacyOutcome)
    assert len(out.facts) == 1
    assert out.facts[0]["fact"] == "Lives in Easton"
    assert out.facts[0]["canonical"]["predicate"] == "home_city"


def test_returns_empty_outcome_on_no_facts(monkeypatch):
    _fake_llm(monkeypatch, [])
    _fake_supabase(monkeypatch)
    out = asyncio.run(memory_extractor.extract_and_save_core_facts("u1", "msg", "reply"))
    assert out.status == "empty" and out.facts == []


def test_never_raises_returns_error_outcome(monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("llm down")
    monkeypatch.setattr(memory_extractor.claude, "send_message", boom)
    out = asyncio.run(memory_extractor.extract_and_save_core_facts("u1", "msg", "reply"))
    assert out.status == "error" and out.facts == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_legacy_outcome.py -q`
Expected: FAIL (`cannot import name 'LegacyOutcome'` / returns None).

- [ ] **Step 3: Refactor `extract_and_save_core_facts`**

In `app/memory_extractor.py`:

1. Add at module level:

```python
from dataclasses import dataclass, field


@dataclass
class LegacyOutcome:
    status: str
    facts: list[dict] = field(default_factory=list)
```

2. Change the signature to `-> LegacyOutcome` and reshape the control flow so it returns an outcome at every exit, **carrying the validated facts, without changing the write logic**:
   - After the validation comprehension builds the `facts` list (the `[{**f, "sensitivity": ...}]` step), keep a reference `parsed = facts`.
   - Every early `return` becomes `return LegacyOutcome(status=<reason>, facts=parsed)` — `"empty"` when parse/validation yields nothing (`parsed=[]`), `"capped"` at the 50-cap, `"duplicate"`/`"empty"` when `to_insert` is empty, `"inserted"` after the POST.
   - The outer `except Exception` returns `LegacyOutcome(status="error", facts=[])` (still logs, still never raises).
   - Do NOT alter the dedup, cap, `should_collect`, header, or POST logic — only the return statements and the `parsed` capture.

- [ ] **Step 4: Run to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_legacy_outcome.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add app/memory_extractor.py tests/test_legacy_outcome.py
git commit -m "feat(memory): extract_and_save_core_facts returns LegacyOutcome (legacy write unchanged)"
```

---

### Task 3: `shadow_ledger.run` — the hermetic shadow core

**Files:**
- Create: `app/shadow_ledger.py`
- Test: `tests/test_shadow_ledger.py`

**Interfaces:**
- Consumes: `LegacyOutcome`, `map_canonical`, `apply_candidate_durably`, `LedgerContext`, `should_collect`.
- Produces: `async run(outcome, *, owner_user_id, exchange_id, executor, settings, now=None) -> dict` — for each fact with a valid `canonical` object that passes `should_collect`, maps it to a `Candidate` and applies it durably; returns a summary `{"considered", "applied", "unmapped", "gated", "errors"}`. Never raises.

- [ ] **Step 1: Write the failing test**

Create `tests/test_shadow_ledger.py`:

```python
import asyncio
from datetime import date

import pytest

from app import shadow_ledger
from app.memory_extractor import LegacyOutcome
from app.canonical.repository import PsycopgExecutor

EXTRACTOR_VERSION = shadow_ledger.EXTRACTOR_VERSION
_MISSING = object()


class _SpyExecutor:
    """Counts DB calls; optionally delegates to a real executor."""
    def __init__(self, inner=None):
        self.inner = inner
        self.fetch_calls = 0
        self.apply_calls = 0

    async def fetch_active_facts(self, *a):
        self.fetch_calls += 1
        return await self.inner.fetch_active_facts(*a) if self.inner else []

    async def apply_delta(self, *a, **kw):
        self.apply_calls += 1
        return await self.inner.apply_delta(*a, **kw) if self.inner else {"ok": True}


def _fact(canonical=None, sensitivity="none"):
    f = {"category": "location", "fact": "Lives in Easton", "sensitivity": sensitivity}
    if canonical is not None:
        f["canonical"] = canonical
    return f


_HOME = {"subject_type": "user", "predicate": "home_city", "value_json": {"city": "Easton"},
         "confirmation_status": "explicitly_stated"}

_OPEN = {}  # collection fully enabled


def _run(ledger_db, outcome, settings=_OPEN):
    ex = PsycopgExecutor(ledger_db)
    return asyncio.run(shadow_ledger.run(
        outcome, owner_user_id="u1", exchange_id="ex1", executor=ex,
        settings=settings, now=date(2026, 1, 1)))


def _active(ledger_db, predicate="home_city"):
    ex = PsycopgExecutor(ledger_db)
    return asyncio.run(ex.fetch_active_facts("u1", "user", "self", predicate, "global", None))


def test_maps_and_applies_a_canonical_fact(ledger_db):
    summ = _run(ledger_db, LegacyOutcome("inserted", [_fact(_HOME)]))
    assert summ["applied"] == 1
    assert len(_active(ledger_db)) == 1


@pytest.mark.parametrize("canonical", [_MISSING, None, {}, "garbage", {"predicate": 123}])
def test_absent_or_malformed_canonical_is_zero_db_activity(ledger_db, canonical):
    spy = _SpyExecutor(PsycopgExecutor(ledger_db))
    f = {"category": "personal", "fact": "Ben likes pickleball", "sensitivity": "none"}
    if canonical is not _MISSING:
        f["canonical"] = canonical
    summ = asyncio.run(shadow_ledger.run(
        LegacyOutcome("inserted", [f]), owner_user_id="u1", exchange_id="ex1",
        executor=spy, settings=_OPEN, now=date(2026, 1, 1)))
    assert summ["applied"] == 0 and summ["unmapped"] == 1
    assert spy.fetch_calls == 0 and spy.apply_calls == 0       # dormant plumbing: zero DB activity
    assert len(_active(ledger_db)) == 0


def test_idempotent_replay_same_exchange_creates_no_duplicate(ledger_db):
    # Simulates a timeout-after-commit retry: the SAME exchange_id + fact, applied twice,
    # must yield exactly one active version (dedup on reload + idempotency index).
    ex = PsycopgExecutor(ledger_db)
    out = LegacyOutcome("inserted", [_fact(_HOME)])

    async def body():
        await shadow_ledger.run(out, owner_user_id="u1", exchange_id="ex1", executor=ex,
                                settings=_OPEN, now=date(2026, 1, 1))
        await shadow_ledger.run(out, owner_user_id="u1", exchange_id="ex1", executor=ex,
                                settings=_OPEN, now=date(2026, 2, 1))  # replay

    asyncio.run(body())
    assert len(_active(ledger_db)) == 1                          # exactly one — no duplicate


def test_gated_fact_is_not_applied(ledger_db):
    # settings disable the 'location' sensitivity class → should_collect False
    settings = {"disabled_sensitivities": ["location"]}
    summ = _run(ledger_db, LegacyOutcome("inserted", [_fact(_HOME, sensitivity="location")]),
                settings=settings)
    assert summ["gated"] == 1 and summ["applied"] == 0
    assert len(_active(ledger_db)) == 0


def test_fail_open_on_executor_error(ledger_db):
    class _Boom:
        async def fetch_active_facts(self, *a):
            raise RuntimeError("db down")
        async def apply_delta(self, *a, **kw):
            raise RuntimeError("db down")

    async def body():
        return await shadow_ledger.run(
            LegacyOutcome("inserted", [_fact(_HOME)]), owner_user_id="u1",
            exchange_id="ex1", executor=_Boom(), settings=_OPEN, now=date(2026, 1, 1))

    summ = asyncio.run(body())     # must NOT raise
    assert summ["errors"] == 1 and summ["applied"] == 0


def test_capped_legacy_still_shadows(ledger_db):
    # Even when legacy status is 'capped', the shadow path processes the facts.
    summ = _run(ledger_db, LegacyOutcome("capped", [_fact(_HOME)]))
    assert summ["applied"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_shadow_ledger.py -q`
Expected: FAIL (`No module named 'app.shadow_ledger'`).

- [ ] **Step 3: Write `app/shadow_ledger.py`**

```python
"""Shadow ledger runner — maps a turn's extracted facts into the canonical ledger.

Invoked from the post-chat background task AFTER the legacy write. Invisible and
fail-open: it never raises into the caller, and a fact without a valid `canonical`
object (the case in production until the nested-prompt ships) is a no-op.
"""
from __future__ import annotations

import logging
from datetime import date

from app.canonical.mapper import map_canonical
from app.canonical.repository import (LedgerContext, apply_candidate_durably,
                                      ENGINE_VERSION)
from app import memory_settings

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "core-facts-2026-07-14"


async def run(outcome, *, owner_user_id: str, exchange_id: str, executor,
              settings: dict, now: date | None = None) -> dict:
    summary = {"considered": 0, "applied": 0, "unmapped": 0, "gated": 0, "errors": 0}
    facts = getattr(outcome, "facts", None) or []
    for f in facts:
        summary["considered"] += 1
        try:
            canonical = f.get("canonical") if isinstance(f, dict) else None
            sensitivity = (f.get("sensitivity") if isinstance(f, dict) else None) or "none"
            candidate = map_canonical(canonical, sensitivity=sensitivity, now=now)
            if candidate is None:
                summary["unmapped"] += 1
                continue
            if not memory_settings.should_collect(settings, candidate.sensitivity):
                summary["gated"] += 1
                continue
            ctx = LedgerContext(owner_user_id=owner_user_id, source_exchange_id=exchange_id,
                                extractor_version=EXTRACTOR_VERSION,
                                sensitivity=candidate.sensitivity)
            await apply_candidate_durably(executor, candidate, ctx, now=now)
            summary["applied"] += 1
        except Exception as exc:  # fail-open: never propagate into the caller
            summary["errors"] += 1
            logger.warning("[shadow_ledger] apply failed exchange=%s: %r", exchange_id, exc)
    return summary
```

- [ ] **Step 4: Run to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_shadow_ledger.py -q`
Expected: PASS (10 passed — the parametrized zero-DB-activity case counts as 5).

- [ ] **Step 5: Commit**

```bash
git add app/shadow_ledger.py tests/test_shadow_ledger.py
git commit -m "feat(shadow): shadow_ledger.run — gate, map, apply durably, fail-open, no-op without canonical"
```

---

### Task 4: Wire into `chat.py` + `exchange_id` on the archive

**Files:**
- Modify: `app/routers/chat.py`
- Modify: `app/conversation_store.py`
- Test: `tests/test_shadow_wiring.py`

**Interfaces:**
- Produces: `_extract_and_shadow(user_id, message, reply, exchange_id)` bg helper in `chat.py` — awaits `extract_and_save_core_facts`, then runs `shadow_ledger.run` (via a `PostgrestExecutor`, `should_collect` settings loaded once, wrapped in `asyncio.wait_for(SHADOW_TIMEOUT)`), swallowing everything. The streaming and non-streaming handlers are **mutually exclusive** (a request hits exactly one), so each handler mints **one** `exchange_id = uuid4().hex` for the whole turn and passes that **same variable** to BOTH `_extract_and_shadow` and `conversation_store.save_exchange` — never a fresh id per call. `save_exchange` stamps each archived message dict with `"id"` derived from the exchange id. (A sortable UUIDv7 would be a nice future refinement but is out of scope for 3b.)

- [ ] **Step 1: Write the failing test**

Create `tests/test_shadow_wiring.py`:

```python
import asyncio
from app.routers import chat


def test_extract_and_shadow_runs_shadow_after_legacy(monkeypatch):
    calls = []

    async def fake_extract(user_id, msg, reply):
        calls.append("legacy")
        from app.memory_extractor import LegacyOutcome
        return LegacyOutcome("inserted", [{"fact": "x", "sensitivity": "none"}])

    async def fake_run(outcome, **kw):
        calls.append(("shadow", kw["exchange_id"], len(outcome.facts)))
        return {"applied": 0}

    monkeypatch.setattr(chat.memory_extractor, "extract_and_save_core_facts", fake_extract)
    monkeypatch.setattr(chat.shadow_ledger, "run", fake_run)

    asyncio.run(chat._extract_and_shadow("u1", "msg", "reply", "exABC"))
    assert calls[0] == "legacy"                       # legacy first
    assert calls[1] == ("shadow", "exABC", 1)         # shadow after, same exchange id


def test_extract_and_shadow_never_raises(monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("down")
    monkeypatch.setattr(chat.memory_extractor, "extract_and_save_core_facts", boom)
    asyncio.run(chat._extract_and_shadow("u1", "msg", "reply", "exABC"))  # must not raise


def test_save_exchange_stamps_message_id(monkeypatch):
    from app import conversation_store
    captured = {}

    async def fake_rpc(client, user_id, companion_id, session_id, new_msgs):
        captured["msgs"] = new_msgs
        return True

    monkeypatch.setattr(conversation_store, "_save_via_rpc", fake_rpc)
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "key")
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _NoClient())

    asyncio.run(conversation_store.save_exchange("u1", "c1", "s1", "hi", "hello",
                                                 exchange_id="exABC"))
    ids = [m.get("id") for m in captured["msgs"]]
    assert ids == ["exABC:user", "exABC:assistant"]


class _NoClient:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_shadow_wiring.py -q`
Expected: FAIL (`_extract_and_shadow` / `exchange_id` param not present).

- [ ] **Step 3: Add the bg wrapper + timeout const to `chat.py`**

Near the other module constants:

```python
import uuid
from app import shadow_ledger
from app.canonical.repository import PostgrestExecutor

SHADOW_TIMEOUT_SECONDS = 8.0


async def _extract_and_shadow(user_id: str, message: str, reply: str, exchange_id: str) -> None:
    """Legacy core-facts write, then the (fail-open, no-op-until-3c) shadow ledger."""
    try:
        outcome = await memory_extractor.extract_and_save_core_facts(user_id, message, reply)
    except Exception:
        _chat_logger.warning("core-facts extraction failed user=%.8s", user_id)
        return
    try:
        settings = await memory_settings.get_settings(user_id)
        await asyncio.wait_for(
            shadow_ledger.run(outcome, owner_user_id=user_id, exchange_id=exchange_id,
                              executor=PostgrestExecutor(), settings=settings),
            timeout=SHADOW_TIMEOUT_SECONDS)
    except Exception:
        _chat_logger.warning("shadow ledger skipped user=%.8s exchange=%s", user_id, exchange_id)
```

(Requires `from app import memory_settings` — add if not already imported.)

- [ ] **Step 4: Replace both `extract_and_save_core_facts` call sites**

At the non-streaming site (~chat.py:1189) and the streaming site (~chat.py:1476), replace:

```python
    asyncio.create_task(_bg(
        memory_extractor.extract_and_save_core_facts(user_id, request.message, reply)))
```

with a per-turn exchange id threaded through both the shadow wrapper and the archive:

```python
    exchange_id = uuid.uuid4().hex
    asyncio.create_task(_bg(_extract_and_shadow(user_id, request.message, reply, exchange_id)))
```

and update the corresponding `conversation_store.save_exchange(...)` call in that handler to pass `exchange_id=exchange_id`. (Use `user_message`/`full_text` at the streaming site.)

- [ ] **Step 5: Add `exchange_id` to `save_exchange`**

In `app/conversation_store.py`, give `save_exchange` an optional `exchange_id: str | None = None` param, and when building `new_msgs`, stamp each with an id:

```python
        new_msgs = [
            {"role": "user",      "content": user_message,    "ts": ts,
             "id": f"{exchange_id}:user" if exchange_id else None},
            {"role": "assistant", "content": assistant_reply, "ts": ts,
             "id": f"{exchange_id}:assistant" if exchange_id else None},
        ]
```

(Leave the rest of `save_exchange` — RPC + fetch/patch fallback — unchanged.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_shadow_wiring.py -q`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add app/routers/chat.py app/conversation_store.py tests/test_shadow_wiring.py
git commit -m "feat(shadow): wire shadow_ledger + per-turn exchange_id into chat + archive"
```

---

### Task 5: Full-suite green gate + finish

- [ ] **Step 1: Run the entire suite + benchmark**

Run: `./venv/bin/python -m pytest tests/ -q && ./venv/bin/python -m benchmark.runner`
Expected: all pass; benchmark `A1: 13/13 scenarios passed. Hard gates: clean.`

- [ ] **Step 2: Confirm the legacy write logic is untouched**

Run: `git diff origin/main...HEAD -- app/memory_extractor.py` and confirm the diff only adds `LegacyOutcome` + reshapes `return` statements + captures `parsed` — the LLM prompt, validation, dedup, 50-cap, headers, and POST body are unchanged.

- [ ] **Step 3: Finish the branch**

Announce and use **superpowers:finishing-a-development-branch**. In the finish summary, state clearly: **this stage changes live control flow, so it requires a Republish to deploy** (unlike 1/2/3a); the legacy path is behavior-preserved and the shadow path is a **no-op in production until 3c** (no `canonical` object is emitted yet), so it is safe to deploy but does nothing user-visible and writes nothing to the ledger yet.

---

## Roadmap — final Stage-3 plan

- **3c — prompt + A/B gate:** extend `_CORE_FACTS_SYSTEM` to emit the nested `canonical{}` object behind a runtime toggle; the offline A/B corpus harness (run with LLM creds) asserting legacy capture-rate/precision/category/sensitivity/JSON-failure don't regress past a threshold; on pass, flip the toggle — the shadow ledger then starts recording real traffic. Carries the 3a checklist's remaining items (autocommit/concurrency docstrings, retry backoff, empty-config guard, an `asyncio.gather` 23505 race test).

## Carry-forward from the Stage-3b whole-branch review (Opus: ready-to-merge, no must-fix)

All five binding invariants verified with honest tests (legacy write byte-identical, shadow fail-open + reaches-no-user, no-op-without-`canonical`, at-most-once/timeout-safe, one `exchange_id`/turn shared with the archive). Fixed before merge: `get_settings` moved inside the `wait_for` timeout; the wiring test made env-independent + hermetic (no network); and the shadow path now **short-circuits before any DB call when no fact carries `canonical`** (true zero-DB in prod until 3c). Deferred (safe, address in 3c):

- **Error-path completeness:** `extract_and_save_core_facts`'s outer `except` returns `facts=[]`, so if the LLM parse succeeded but the Supabase write later throws, the shadow ledger under-records that turn (shadow completeness is coupled to legacy write success). Rare + best-effort; to decouple, capture `parsed` in a scope the `except` sees and return `facts=parsed` on post-parse errors.
- **Overloaded `"duplicate"` status** (also covers the all-gated-out case) and the happy-path `LegacyOutcome` test not asserting `status` — cosmetic; `shadow_ledger.run` consumes `facts`, never `status`.
- **The 3a checklist** (autocommit/concurrency docstrings on `PsycopgExecutor`, retry backoff/jitter, empty `SUPABASE_URL`/`SERVICE_KEY` guard, and an `asyncio.gather`-based **23505 insert-race** test against `ledger_db` — the replay test today is sequential) — resolve when 3c makes the path live under real concurrency.
- **No 50-cap on the ledger (intentional):** `test_capped_legacy_still_shadows` encodes that a legacy 50-fact cap must NOT suppress shadowing — keep this invariant visible in 3c.
