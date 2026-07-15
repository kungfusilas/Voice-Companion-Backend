# Canonical Ledger Shadow Mode — Plan 3a: Repository (persistence-backed apply)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `app/canonical/repository.py` — the async layer that loads a candidate's active facts from the ledger, runs the Stage-1 engine, and applies the resulting delta via `apply_canonical_delta` with retry-on-conflict — behind a transport seam so its full orchestration is **proven end-to-end against a real local Postgres**, while the production PostgREST/httpx transport is thin, fake-tested glue.

**Architecture:** Stage 3a of the shadow-mode rollout (spec: `docs/superpowers/specs/2026-07-14-canonical-ledger-shadow-mode-design.md`; Stage-2 carry-forward contract at the bottom of `docs/superpowers/plans/2026-07-14-canonical-ledger-shadow-schema.md`). A `LedgerExecutor` protocol has two impls: `PsycopgExecutor` (tests, direct SQL against the local ephemeral Postgres from Plan 2's harness) and `PostgrestExecutor` (prod, httpx→Supabase, mirroring `conversation_store`). The repository's `apply_candidate_durably` does load → `apply_candidate` → `compute_delta` → `apply_delta`, retrying on a `ConflictError` (SQLSTATE `40001` CAS conflict OR `23505` insert race). This plan touches **no** live app code — `repository.py` is new and imported nowhere yet (Stage 3b wires it in).

**Tech Stack:** Python async, psycopg 3, httpx, pytest (async driven via `asyncio.run`, no new deps).

## Global Constraints

- **No live app code touched.** New module `app/canonical/repository.py` + its tests only. Nothing imports it yet.
- **The engine still decides truth.** The repository orchestrates load/apply/persist; it adds no lifecycle logic.
- **Honor the Stage-2 carry-forward contract:** retry on **both** `40001` and `23505`; a **date-aware** JSON encoder before the RPC (`compute_delta` emits Python `date` objects); **enrich events** with `owner_user_id` + `source_exchange_id` + versions; **never NULL** the idempotency-key columns (`source_exchange_id`, `extractor_version`); use `subject_id="self"` (align with the DB default, not `Candidate`'s `"user"` default).
- **pg-backed tests** use Plan 2's `ledger_db` fixture and skip gracefully if `postgresql@16` is absent. Pure/offline tests stay green.
- Run all commands from `artifacts/voice-companion/` via `./venv/bin/python`.

---

## File Structure

- Create `app/canonical/repository.py` — `ConflictError`, `LedgerExecutor` (Protocol), `LedgerContext`, row↔Fact mapping, payload builders, `PsycopgExecutor`, `PostgrestExecutor`, `apply_candidate_durably`.
- Create `tests/test_repository_executor.py` — PsycopgExecutor round-trip + mapping (against local pg).
- Create `tests/test_repository_apply.py` — `apply_candidate_durably` load/apply/persist + retry-on-conflict (against local pg).
- Create `tests/test_postgrest_executor.py` — prod transport payloads + error→ConflictError mapping (fake httpx).

---

### Task 1: Executor seam + PsycopgExecutor

**Files:**
- Create: `app/canonical/repository.py`
- Test: `tests/test_repository_executor.py`

**Interfaces:**
- Produces: `ConflictError(Exception)`; `LedgerExecutor` Protocol with `async fetch_active_facts(owner_user_id, subject_type, subject_id, predicate, scope, companion_id) -> list[dict]` and `async apply_delta(supersedes, updates, inserts, events) -> dict`; `PsycopgExecutor(conn)` (wraps a sync psycopg connection via `asyncio.to_thread`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_repository_executor.py`:

```python
import asyncio
import pathlib

from app.canonical.repository import PsycopgExecutor, ConflictError

_MIG = pathlib.Path(__file__).parent.parent / "migrations" / "0002_canonical_ledger_shadow.sql"


def _insert_row(**over):
    row = dict(owner_user_id="u1", subject_type="user", subject_id="self",
               predicate="home_city", cardinality="single",
               value_json={"city": "Easton"}, normalized_value='{"city":"easton"}',
               status="active", scope="global", version=1,
               source_exchange_id="ex1", extractor_version="v1")
    row.update(over)
    return row


def test_apply_delta_insert_then_fetch(ledger_db):
    ex = PsycopgExecutor(ledger_db)

    async def body():
        res = await ex.apply_delta(supersedes=[], updates=[], inserts=[_insert_row()],
                                   events=[])
        assert res["inserted"] == 1
        rows = await ex.fetch_active_facts("u1", "user", "self", "home_city", "global", None)
        assert len(rows) == 1 and rows[0]["value_json"] == {"city": "Easton"}

    asyncio.run(body())


def test_apply_delta_stale_supersede_raises_conflicterror(ledger_db):
    ex = PsycopgExecutor(ledger_db)

    async def body():
        await ex.apply_delta(supersedes=[], updates=[], inserts=[
            _insert_row(id="11111111-1111-1111-1111-111111111111")], events=[])
        try:
            await ex.apply_delta(
                supersedes=[{"id": "11111111-1111-1111-1111-111111111111",
                             "expected_version": 99, "new_status": "superseded"}],
                updates=[], inserts=[], events=[])
            assert False, "expected ConflictError"
        except ConflictError:
            pass

    asyncio.run(body())
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_repository_executor.py -q`
Expected: FAIL (`No module named 'app.canonical.repository'`).

- [ ] **Step 3: Write the executor core in `app/canonical/repository.py`**

```python
"""Repository — persistence-backed application of engine candidates to the ledger.

Production talks to Supabase via PostgREST/httpx (PostgrestExecutor); tests use a
direct psycopg connection to a local Postgres (PsycopgExecutor). The retry loop
reloads and recomputes on a conflict — a stale-version CAS abort (SQLSTATE 40001)
or a real insert race (23505) — both surfaced as ConflictError.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from typing import Any, Protocol


class ConflictError(Exception):
    """The ledger signalled a retryable conflict (CAS 40001 or unique-violation 23505)."""


_CONFLICT_SQLSTATES = {"40001", "23505"}


class LedgerExecutor(Protocol):
    async def fetch_active_facts(self, owner_user_id: str, subject_type: str,
                                 subject_id: str, predicate: str, scope: str,
                                 companion_id: str | None) -> list[dict]: ...

    async def apply_delta(self, supersedes: list[dict], updates: list[dict],
                          inserts: list[dict], events: list[dict]) -> dict: ...


def _json(value: Any) -> str:
    """date-aware JSON encoder (the engine/delta emit Python date objects)."""
    def default(o):
        if isinstance(o, date):
            return o.isoformat()
        raise TypeError(f"not JSON-serializable: {type(o)}")
    return json.dumps(value, default=default)


class PsycopgExecutor:
    """Test/local executor over a sync psycopg connection (async via to_thread)."""

    _COLS = ("id", "owner_user_id", "subject_type", "subject_id", "predicate",
             "cardinality", "value_json", "normalized_value", "sub_key", "status",
             "scope", "companion_id", "valid_from", "valid_until", "observed_at",
             "supersedes_fact_id", "confirmation_status", "sensitivity", "version",
             "extractor_version", "mapper_version", "engine_version",
             "registry_version", "decision_reason", "source_exchange_id")

    def __init__(self, conn):
        self._conn = conn

    async def fetch_active_facts(self, owner_user_id, subject_type, subject_id,
                                 predicate, scope, companion_id):
        return await asyncio.to_thread(self._fetch, owner_user_id, subject_type,
                                       subject_id, predicate, scope, companion_id)

    def _fetch(self, owner_user_id, subject_type, subject_id, predicate, scope, companion_id):
        sql = (f"SELECT {', '.join(self._COLS)} FROM canonical_facts "
               "WHERE owner_user_id=%s AND subject_type=%s AND subject_id=%s "
               "AND predicate=%s AND scope=%s AND status='active' "
               "AND companion_id IS NOT DISTINCT FROM %s")
        cur = self._conn.execute(sql, [owner_user_id, subject_type, subject_id,
                                       predicate, scope, companion_id])
        return [dict(zip(self._COLS, r)) for r in cur.fetchall()]

    async def apply_delta(self, supersedes, updates, inserts, events):
        return await asyncio.to_thread(self._apply, supersedes, updates, inserts, events)

    def _apply(self, supersedes, updates, inserts, events):
        import psycopg
        try:
            row = self._conn.execute(
                "SELECT apply_canonical_delta(%s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)",
                [_json(supersedes), _json(updates), _json(inserts), _json(events)],
            ).fetchone()[0]
            return row
        except psycopg.Error as exc:
            if getattr(exc, "sqlstate", None) in _CONFLICT_SQLSTATES:
                raise ConflictError(str(exc)) from exc
            raise
```

- [ ] **Step 4: Run to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_repository_executor.py -q`
Expected: PASS (2 passed). If skipped, install `postgresql@16`.

- [ ] **Step 5: Commit**

```bash
git add app/canonical/repository.py tests/test_repository_executor.py
git commit -m "feat(ledger): repository executor seam + PsycopgExecutor (local-pg)"
```

---

### Task 2: Fact↔row mapping + delta→payload builders

**Files:**
- Modify: `app/canonical/repository.py`
- Test: `tests/test_repository_executor.py` (add cases)

**Interfaces:**
- Consumes: `models.Fact`, `PsycopgExecutor` (Task 1).
- Produces: `LedgerContext` dataclass (`owner_user_id`, `source_exchange_id`, `extractor_version`, `sensitivity`); `row_to_fact(row) -> Fact`; `fact_to_insert(fact, ctx) -> dict`; `enrich_event(ev, ctx) -> dict`; version constants `ENGINE_VERSION`, `MAPPER_VERSION`, `REGISTRY_VERSION`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_repository_executor.py`:

```python
from datetime import date
from app.canonical.repository import (LedgerContext, row_to_fact, fact_to_insert,
                                      enrich_event)
from app.canonical.models import Fact


def _ctx():
    return LedgerContext(owner_user_id="u1", source_exchange_id="ex1",
                         extractor_version="v1", sensitivity="none")


def test_row_to_fact_parses_dates_and_json():
    f = row_to_fact({"id": "abc", "subject_type": "user", "subject_id": "self",
                     "predicate": "home_city", "cardinality": "single",
                     "value_json": {"city": "Easton"}, "normalized_value": '{"city":"easton"}',
                     "sub_key": None, "status": "active", "scope": "global",
                     "companion_id": None, "valid_from": "2026-06-01", "valid_until": None,
                     "observed_at": date(2026, 7, 1), "supersedes_fact_id": None,
                     "confirmation_status": "inferred", "sensitivity": "none", "version": 3})
    assert f.id == "abc" and f.value_json == {"city": "Easton"}
    assert f.valid_from == date(2026, 6, 1) and f.observed_at == date(2026, 7, 1)
    assert f.version == 3


def test_fact_to_insert_serializes_dates_and_injects_context():
    f = Fact(id="x", subject_type="user", subject_id="self", predicate="home_city",
             value_json={"city": "Easton"}, normalized_value='{"city":"easton"}',
             cardinality="single", valid_from=date(2026, 6, 1))
    d = fact_to_insert(f, _ctx())
    assert d["owner_user_id"] == "u1" and d["source_exchange_id"] == "ex1"
    assert d["extractor_version"] == "v1" and d["engine_version"]
    assert d["valid_from"] == "2026-06-01"          # ISO string, not a date object
    assert d["value_json"] == {"city": "Easton"}    # jsonb stays structured


def test_enrich_event_injects_owner_and_exchange():
    ev = enrich_event({"event_type": "fact_created", "fact_id": "x"}, _ctx())
    assert ev["owner_user_id"] == "u1" and ev["source_exchange_id"] == "ex1"
    assert ev["event_type"] == "fact_created"
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_repository_executor.py -q`
Expected: FAIL (`cannot import name 'LedgerContext'`).

- [ ] **Step 3: Add mapping + builders to `app/canonical/repository.py`**

Add near the top (after imports):

```python
from dataclasses import dataclass

from app.canonical.models import Fact

ENGINE_VERSION = "engine-2026-07-14"
MAPPER_VERSION = "mapper-2026-07-14"
REGISTRY_VERSION = "registry-2026-07-14"


@dataclass
class LedgerContext:
    owner_user_id: str
    source_exchange_id: str
    extractor_version: str
    sensitivity: str = "none"


def _as_date(v):
    if v is None or isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def row_to_fact(row: dict) -> Fact:
    return Fact(
        id=str(row["id"]),
        subject_type=row["subject_type"], subject_id=row["subject_id"],
        predicate=row["predicate"], value_json=row["value_json"],
        normalized_value=row["normalized_value"], status=row.get("status", "active"),
        scope=row.get("scope", "global"), companion_id=row.get("companion_id"),
        valid_from=_as_date(row.get("valid_from")), valid_until=_as_date(row.get("valid_until")),
        observed_at=_as_date(row.get("observed_at")),
        supersedes_fact_id=(str(row["supersedes_fact_id"]) if row.get("supersedes_fact_id") else None),
        confirmation_status=row.get("confirmation_status", "inferred"),
        sensitivity=row.get("sensitivity", "none"), sub_key=row.get("sub_key"),
        cardinality=row.get("cardinality", "single"), version=int(row.get("version", 1)),
    )


def _iso(d):
    return d.isoformat() if isinstance(d, date) else None


def fact_to_insert(f: Fact, ctx: LedgerContext) -> dict:
    return {
        "id": f.id, "owner_user_id": ctx.owner_user_id,
        "subject_type": f.subject_type, "subject_id": f.subject_id,
        "predicate": f.predicate, "cardinality": f.cardinality,
        "value_json": f.value_json, "normalized_value": f.normalized_value,
        "sub_key": f.sub_key, "status": f.status, "scope": f.scope,
        "companion_id": f.companion_id, "valid_from": _iso(f.valid_from),
        "valid_until": _iso(f.valid_until), "observed_at": _iso(f.observed_at),
        "supersedes_fact_id": f.supersedes_fact_id,
        "confirmation_status": f.confirmation_status, "sensitivity": f.sensitivity,
        "version": f.version, "extractor_version": ctx.extractor_version,
        "mapper_version": MAPPER_VERSION, "engine_version": ENGINE_VERSION,
        "registry_version": REGISTRY_VERSION, "source_exchange_id": ctx.source_exchange_id,
    }


def enrich_event(ev: dict, ctx: LedgerContext) -> dict:
    return {**ev, "owner_user_id": ctx.owner_user_id,
            "source_exchange_id": ctx.source_exchange_id,
            "extractor_version": ev.get("extractor_version", ctx.extractor_version),
            "mapper_version": ev.get("mapper_version", MAPPER_VERSION),
            "registry_version": ev.get("registry_version", REGISTRY_VERSION)}
```

- [ ] **Step 4: Run to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_repository_executor.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/canonical/repository.py tests/test_repository_executor.py
git commit -m "feat(ledger): Fact<->row mapping + date-aware delta payload builders"
```

---

### Task 3: `apply_candidate_durably` — load/apply/persist with retry

**Files:**
- Modify: `app/canonical/repository.py`
- Test: `tests/test_repository_apply.py`

**Interfaces:**
- Consumes: engine `apply_candidate`, `compute_delta`, mapping/builders (Tasks 1–2).
- Produces: `async apply_candidate_durably(executor, candidate, ctx, now=None, max_retries=3) -> dict`. Loads the candidate's active slot, runs the engine, persists the delta; on `ConflictError` reloads and recomputes up to `max_retries`, then re-raises.

- [ ] **Step 1: Write the failing test**

Create `tests/test_repository_apply.py`:

```python
import asyncio
from datetime import date

from app.canonical.repository import (PsycopgExecutor, LedgerContext,
                                      apply_candidate_durably, ConflictError)
from app.canonical.models import Candidate


def _ctx(ex_id="ex1"):
    return LedgerContext(owner_user_id="u1", source_exchange_id=ex_id, extractor_version="v1")


def _home(city, conf="explicitly_stated"):
    return Candidate(subject_type="user", subject_id="self", predicate="home_city",
                     value_json={"city": city}, confirmation_status=conf)


def _active(ex):
    return asyncio.run(ex.fetch_active_facts("u1", "user", "self", "home_city", "global", None))


def test_durable_insert_then_supersede(ledger_db):
    ex = PsycopgExecutor(ledger_db)

    async def body():
        await apply_candidate_durably(ex, _home("Easton"), _ctx("ex1"), now=date(2026, 1, 1))
        await apply_candidate_durably(ex, _home("Reading"), _ctx("ex2"), now=date(2026, 2, 1))

    asyncio.run(body())
    rows = _active(ex)
    assert len(rows) == 1 and rows[0]["value_json"] == {"city": "Reading"}


def test_durable_dedup_is_noop(ledger_db):
    ex = PsycopgExecutor(ledger_db)

    async def body():
        await apply_candidate_durably(ex, _home("Easton"), _ctx("ex1"), now=date(2026, 1, 1))
        await apply_candidate_durably(ex, _home("Easton"), _ctx("ex2"), now=date(2026, 2, 1))

    asyncio.run(body())
    assert len(_active(ex)) == 1


class _FlakyExecutor:
    """Delegates to a real executor but raises ConflictError on the first apply_delta."""
    def __init__(self, inner):
        self._inner = inner
        self.apply_calls = 0

    async def fetch_active_facts(self, *a):
        return await self._inner.fetch_active_facts(*a)

    async def apply_delta(self, *a, **kw):
        self.apply_calls += 1
        if self.apply_calls == 1:
            raise ConflictError("simulated conflict")
        return await self._inner.apply_delta(*a, **kw)


def test_durable_retries_on_conflict(ledger_db):
    ex = _FlakyExecutor(PsycopgExecutor(ledger_db))

    async def body():
        await apply_candidate_durably(ex, _home("Easton"), _ctx("ex1"), now=date(2026, 1, 1))

    asyncio.run(body())
    assert ex.apply_calls == 2                       # first raised, retry succeeded
    assert len(_active(PsycopgExecutor(ledger_db))) == 1


def test_durable_reraises_after_exhausting_retries(ledger_db):
    class _AlwaysConflict:
        async def fetch_active_facts(self, *a):
            return []
        async def apply_delta(self, *a, **kw):
            raise ConflictError("always")

    async def body():
        try:
            await apply_candidate_durably(_AlwaysConflict(), _home("Easton"),
                                          _ctx("ex1"), now=date(2026, 1, 1), max_retries=3)
            assert False, "expected ConflictError"
        except ConflictError:
            pass

    asyncio.run(body())


def test_durable_recovers_from_a_real_concurrent_supersede(ledger_db):
    # A genuine race: the ledger row is superseded by a competing writer between
    # our load and our apply, so the CAS aborts (40001) and the retry recovers.
    inner = PsycopgExecutor(ledger_db)

    class _RaceOnce:
        def __init__(self):
            self.applied = 0
        async def fetch_active_facts(self, *a):
            return await inner.fetch_active_facts(*a)
        async def apply_delta(self, supersedes, updates, inserts, events):
            self.applied += 1
            if self.applied == 1 and supersedes:
                # competing writer bumps the target row's version first
                sid = supersedes[0]["id"]
                await inner.apply_delta(
                    supersedes=[{"id": sid, "expected_version": 1, "new_status": "superseded"}],
                    updates=[], inserts=[], events=[])
            return await inner.apply_delta(supersedes, updates, inserts, events)

    async def body():
        await apply_candidate_durably(inner, _home("Easton"), _ctx("ex1"), now=date(2026, 1, 1))
        racer = _RaceOnce()
        await apply_candidate_durably(racer, _home("Reading"), _ctx("ex2"), now=date(2026, 2, 1))
        assert racer.applied >= 2                     # first CAS lost the race, retry won

    asyncio.run(body())
    rows = _active(inner)
    assert len(rows) == 1 and rows[0]["value_json"] == {"city": "Reading"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_repository_apply.py -q`
Expected: FAIL (`cannot import name 'apply_candidate_durably'`).

- [ ] **Step 3: Add the retry loop to `app/canonical/repository.py`**

```python
from app.canonical.engine import apply_candidate
from app.canonical.delta import compute_delta


async def apply_candidate_durably(executor, candidate, ctx: LedgerContext,
                                  now: date | None = None, max_retries: int = 3) -> dict:
    """Load the candidate's active slot, run the engine, persist the delta.
    Reloads + recomputes on a ConflictError (CAS 40001 / race 23505)."""
    now = now or datetime.now(timezone.utc).date()
    last_exc: ConflictError | None = None
    for _ in range(max_retries):
        rows = await executor.fetch_active_facts(
            ctx.owner_user_id, candidate.subject_type, candidate.subject_id,
            candidate.predicate, candidate.scope, candidate.companion_id)
        before = [row_to_fact(r) for r in rows]
        after = apply_candidate(before, candidate, now)
        delta = compute_delta(before, after, engine_version=ENGINE_VERSION,
                              candidate_id=ctx.source_exchange_id)
        if delta.is_empty():
            return {"ok": True, "changed": False}
        # Everything handed to the executor must be JSON-safe (no date objects):
        # fact_to_insert already ISO-encodes insert dates; supersede ops still carry
        # a raw date valid_until from compute_delta, so encode it here — otherwise
        # PostgrestExecutor's httpx json= would crash on a temporal supersession.
        supersedes = [{**op, "valid_until": _iso(op.get("valid_until"))}
                      for op in delta.supersedes]
        inserts = [fact_to_insert(f, ctx) for f in delta.inserts]
        events = [enrich_event(e, ctx) for e in delta.events]
        try:
            res = await executor.apply_delta(supersedes, delta.updates, inserts, events)
            return {"ok": True, "changed": True, "result": res}
        except ConflictError as exc:
            last_exc = exc
            continue
    raise last_exc or ConflictError("retry exhausted")
```

- [ ] **Step 4: Run to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_repository_apply.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/canonical/repository.py tests/test_repository_apply.py
git commit -m "feat(ledger): apply_candidate_durably load/apply/persist with retry-on-conflict"
```

---

### Task 4: PostgrestExecutor (production transport)

**Files:**
- Modify: `app/canonical/repository.py`
- Test: `tests/test_postgrest_executor.py`

**Interfaces:**
- Produces: `PostgrestExecutor(base_url, service_key, client_factory=None)` implementing `LedgerExecutor` over httpx→Supabase. GET `/rest/v1/canonical_facts` for `fetch_active_facts`; POST `/rest/v1/rpc/apply_canonical_delta` for `apply_delta`; a response whose body `code` is `40001`/`23505` → `ConflictError`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_postgrest_executor.py`:

```python
import asyncio
import json

import pytest

from app.canonical.repository import PostgrestExecutor, ConflictError


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)
    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self._resp
    async def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self._resp


def _ex(resp):
    fake = _FakeClient(resp)
    return PostgrestExecutor("https://x.supabase.co", "key",
                             client_factory=lambda: fake), fake


def test_fetch_builds_filtered_get():
    ex, fake = _ex(_FakeResp(200, [{"id": "a", "value_json": {"city": "Easton"}}]))
    rows = asyncio.run(ex.fetch_active_facts("u1", "user", "self", "home_city", "global", None))
    assert rows[0]["id"] == "a"
    method, url, kw = fake.calls[0]
    assert method == "GET" and "/rest/v1/canonical_facts" in url
    assert kw["params"]["owner_user_id"] == "eq.u1" and kw["params"]["status"] == "eq.active"


def test_apply_posts_rpc_and_returns_body():
    ex, fake = _ex(_FakeResp(200, {"ok": True, "inserted": 1}))
    res = asyncio.run(ex.apply_delta([], [], [{"predicate": "home_city"}], []))
    method, url, kw = fake.calls[0]
    assert method == "POST" and url.endswith("/rest/v1/rpc/apply_canonical_delta")
    assert kw["json"]["p_inserts"] == [{"predicate": "home_city"}]
    assert res["inserted"] == 1


@pytest.mark.parametrize("code", ["40001", "23505"])
def test_conflict_sqlstate_maps_to_conflicterror(code):
    ex, _ = _ex(_FakeResp(400, {"code": code, "message": "conflict"}))
    with pytest.raises(ConflictError):
        asyncio.run(ex.apply_delta([{"id": "x", "expected_version": 1}], [], [], []))


def test_non_conflict_error_raises_runtimeerror():
    ex, _ = _ex(_FakeResp(500, {"code": "42P01", "message": "undefined_table"}))
    with pytest.raises(RuntimeError):
        asyncio.run(ex.apply_delta([], [], [{"predicate": "x"}], []))
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_postgrest_executor.py -q`
Expected: FAIL (`cannot import name 'PostgrestExecutor'`).

- [ ] **Step 3: Add `PostgrestExecutor` to `app/canonical/repository.py`**

```python
import os


def _default_client_factory():
    import httpx
    return httpx.AsyncClient(timeout=15.0)


class PostgrestExecutor:
    """Production executor over Supabase PostgREST (mirrors app.conversation_store)."""

    def __init__(self, base_url: str | None = None, service_key: str | None = None,
                 client_factory=None):
        self._url = (base_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self._key = service_key or os.environ.get("SUPABASE_SERVICE_KEY", "")
        self._client_factory = client_factory or _default_client_factory

    def _headers(self, prefer="return=representation"):
        return {"apikey": self._key, "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json", "Prefer": prefer}

    async def fetch_active_facts(self, owner_user_id, subject_type, subject_id,
                                 predicate, scope, companion_id):
        params = {"owner_user_id": f"eq.{owner_user_id}",
                  "subject_type": f"eq.{subject_type}", "subject_id": f"eq.{subject_id}",
                  "predicate": f"eq.{predicate}", "scope": f"eq.{scope}",
                  "status": "eq.active", "select": "*"}
        params["companion_id"] = f"eq.{companion_id}" if companion_id else "is.null"
        async with self._client_factory() as client:
            resp = await client.get(f"{self._url}/rest/v1/canonical_facts",
                                    headers=self._headers(prefer=""), params=params)
        if resp.status_code not in (200, 206):
            self._raise(resp)
        return resp.json()

    async def apply_delta(self, supersedes, updates, inserts, events):
        body = {"p_supersedes": supersedes, "p_updates": updates,
                "p_inserts": inserts, "p_events": events}
        async with self._client_factory() as client:
            resp = await client.post(f"{self._url}/rest/v1/rpc/apply_canonical_delta",
                                     headers=self._headers(prefer="return=minimal"), json=body)
        if resp.status_code not in (200, 201, 204):
            self._raise(resp)
        try:
            return resp.json()
        except Exception:
            return {"ok": True}

    def _raise(self, resp):
        code = None
        try:
            code = (resp.json() or {}).get("code")
        except Exception:
            pass
        if code in _CONFLICT_SQLSTATES:
            raise ConflictError(f"ledger conflict {code}")
        raise RuntimeError(f"ledger error HTTP {resp.status_code}: {resp.text[:300]}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_postgrest_executor.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/canonical/repository.py tests/test_postgrest_executor.py
git commit -m "feat(ledger): PostgrestExecutor production transport + conflict mapping"
```

---

### Task 5: Full-suite green gate + finish

- [ ] **Step 1: Run the entire suite + benchmark**

Run: `./venv/bin/python -m pytest tests/ -q && ./venv/bin/python -m benchmark.runner`
Expected: all pass; benchmark `A1: 13/13 scenarios passed. Hard gates: clean.`

- [ ] **Step 2: Confirm scope**

Run: `git diff --name-only origin/main...HEAD | grep -vE '^artifacts/voice-companion/(app/canonical/repository.py|tests/|docs/)'` — expect no output (only the new repository module + tests + docs; nothing else in `app/` touched, nothing imports `repository`).

- [ ] **Step 3: Finish the branch**

Announce and use **superpowers:finishing-a-development-branch**. Report the proven result and note the repository is still **inert** (imported nowhere until Stage 3b); no migration/Republish needed.

---

## Roadmap — remaining Stage-3 plans

- **3b — shadow plumbing:** `LegacyOutcome` refactor of `extract_and_save_core_facts`; per-turn `exchange_id` minting + threading (+ `id` on archived messages); `shadow_ledger.run` (always-run, `asyncio.wait_for` timeout, `should_collect` gating) calling `apply_candidate_durably` via a `PostgrestExecutor`; wired into both chat.py call sites. A **no-op in production until 3c** (extraction emits no `canonical` object yet), so safe to deploy; tested by injecting fixture extraction results.
- **3c — prompt + A/B gate:** nested-`canonical` prompt behind a runtime toggle; the offline A/B corpus harness (run with LLM creds as a deploy gate) asserting legacy metrics don't regress; fallback to a separate call if the gate fails.
