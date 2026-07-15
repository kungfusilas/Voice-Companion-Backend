# Canonical Ledger Shadow Mode — Plan 2: Schema + `apply_canonical_delta` RPC

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the ledger's persistence substrate — the `canonical_facts` + `canonical_fact_events` tables, the three per-cardinality partial unique indexes, and the transactional `apply_canonical_delta` RPC that applies a Stage-1 delta atomically under snapshot-match CAS — and **prove** it against a real (ephemeral, local) Postgres.

**Architecture:** Stage 2 of 5 in the shadow-mode rollout (spec: `docs/superpowers/specs/2026-07-14-canonical-ledger-shadow-mode-design.md`). The Stage-1 engine already produces a `Delta(inserts, supersedes, updates, events)`; this stage persists it. The RPC is a *dumb applicator* — it applies the precomputed delta and lets the unique indexes enforce one-active-row-per-slot; it re-decides no truth. Migration is delivered as `migrations/0002_*.sql` for hand-application in the Supabase SQL Editor (per the `0001` convention); the plpgsql is plain Postgres and transfers 1:1. Tests run against an ephemeral local Postgres 16 via a psycopg-backed pytest fixture (the harness recipe is de-risk-proven).

**Tech Stack:** Postgres 16 (local, via Homebrew `postgresql@16`), plpgsql, `psycopg` 3, pytest.

## Global Constraints

- **Migration is additive + idempotent** (`CREATE TABLE/INDEX IF NOT EXISTS`, `CREATE OR REPLACE FUNCTION`) — safe to re-run in Supabase. Include the standard `0001`-style comment header ("Run once in the Supabase SQL Editor").
- **The RPC decides no truth.** It applies the delta's ops and appends events; the *only* correctness it enforces is atomicity + optimistic CAS + the unique-index invariant. No lifecycle logic.
- **Apply order inside the RPC: supersedes → updates → inserts → events.** Inserts must come after supersedes/updates or a momentary second active row trips `one_active_single`/`one_active_multi`.
- **CAS conflict signalling:** any supersede/update whose `WHERE id = ? AND version = ?` affects 0 rows must `RAISE EXCEPTION ... USING ERRCODE='40001'` (serialization_failure), aborting the whole transaction (including events) so the caller can detect-and-retry.
- **Pure/offline tests stay green:** `./venv/bin/python -m pytest tests/ -q` must remain green. Postgres-backed tests use the `ledger_db` fixture and `pytest.skip` if `postgresql@16` is absent (so a pg-less CI degrades gracefully rather than failing).
- Run all commands from `artifacts/voice-companion/`. The pg binaries live at `/opt/homebrew/opt/postgresql@16/bin` (override with `PG_BIN` env).

## Deviations from the spec (intentional, noted)

- The spec's Stage 2 lists **four** tables. This plan creates only `canonical_facts` + `canonical_fact_events` — the two the RPC writes. `ledger_shadow_divergences` + `ledger_shadow_runs` are **deferred to Stage 4** (observability), where they are actually populated and tested (YAGNI: create tables when they are used).
- `repository.py` (Python load/persist) stays in **Stage 3** per the spec — its httpx→PostgREST path can't be tested against local plain Postgres anyway. Stage 2 proves the RPC directly via psycopg (SQL), which is the risky part.

---

## File Structure

- Create `migrations/0002_canonical_ledger_shadow.sql` — the whole migration (both tables, all indexes, the RPC), grown across T2–T4.
- Create `tests/conftest.py` — `_pg_server` (session ephemeral cluster) + `pg_conn` (clean connection) + `ledger_db` (applies the migration) fixtures.
- Modify `requirements-dev.txt` — add `psycopg[binary]`.
- Create `tests/test_ledger_schema.py` — DDL + unique-index behavior (T2).
- Create `tests/test_apply_canonical_delta.py` — RPC insert/events/idempotency/atomicity (T3) and CAS/ordering/conflict (T4).

---

### Task 1: Ephemeral-Postgres test harness

**Files:**
- Modify: `requirements-dev.txt`
- Create: `tests/conftest.py`
- Test: `tests/test_pg_harness.py`

**Interfaces:**
- Produces: pytest fixtures `_pg_server` (session-scoped; yields a DSN prefix `host=127.0.0.1 port=<p> user=postgres`) and `pg_conn` (function-scoped; a psycopg connection to a freshly-reset `public` schema, autocommit).

- [ ] **Step 1: Add the driver dependency**

Append to `requirements-dev.txt`:

```
psycopg[binary]>=3.2
```

- [ ] **Step 2: Write the failing harness smoke test**

Create `tests/test_pg_harness.py`:

```python
def test_pg_conn_roundtrip(pg_conn):
    pg_conn.execute("CREATE TABLE t (id int primary key, name text)")
    pg_conn.execute("INSERT INTO t VALUES (1, 'ok')")
    row = pg_conn.execute("SELECT name FROM t WHERE id = 1").fetchone()
    assert row[0] == "ok"
```

- [ ] **Step 3: Run it to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_pg_harness.py -q`
Expected: FAIL (`fixture 'pg_conn' not found`).

- [ ] **Step 4: Write the fixtures**

Create `tests/conftest.py`:

```python
import atexit
import os
import shutil
import socket
import subprocess
import tempfile

import pytest

PG_BIN = os.environ.get("PG_BIN", "/opt/homebrew/opt/postgresql@16/bin")
# Postgres on macOS refuses to start multithreaded unless a locale is set.
_ENV = {**os.environ, "LC_ALL": "en_US.UTF-8", "LC_CTYPE": "en_US.UTF-8"}


def _free_port() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return str(port)


def _run(*args):
    subprocess.run(args, check=True, env=_ENV,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


@pytest.fixture(scope="session")
def _pg_server():
    if not os.path.exists(os.path.join(PG_BIN, "pg_ctl")):
        pytest.skip("local postgresql@16 not installed (set PG_BIN)")
    tmp = tempfile.mkdtemp(prefix="ledger_pg.")
    data = os.path.join(tmp, "data")
    log = os.path.join(tmp, "log")
    port = _free_port()
    _run(os.path.join(PG_BIN, "initdb"), "-D", data, "-U", "postgres", "--auth=trust")
    _run(os.path.join(PG_BIN, "pg_ctl"), "-D", data, "-l", log, "-o", f"-p {port}", "-w", "start")

    def _stop():
        subprocess.run([os.path.join(PG_BIN, "pg_ctl"), "-D", data, "-w", "stop"],
                       env=_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        shutil.rmtree(tmp, ignore_errors=True)

    atexit.register(_stop)
    try:
        yield f"host=127.0.0.1 port={port} user=postgres"
    finally:
        _stop()


@pytest.fixture
def pg_conn(_pg_server):
    import psycopg
    with psycopg.connect(f"{_pg_server} dbname=postgres", autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
        yield conn
```

- [ ] **Step 5: Run the smoke test to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_pg_harness.py -q`
Expected: PASS (1 passed). If it skips, `postgresql@16` isn't installed — install with `brew install postgresql@16`.

- [ ] **Step 6: Confirm pure suite unaffected**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: all prior tests still pass + the new harness test (the session pg server starts only because a test requested it).

- [ ] **Step 7: Commit**

```bash
git add requirements-dev.txt tests/conftest.py tests/test_pg_harness.py
git commit -m "test(ledger): ephemeral local-postgres pytest harness"
```

---

### Task 2: Migration DDL — tables + partial unique indexes

**Files:**
- Create: `migrations/0002_canonical_ledger_shadow.sql`
- Modify: `tests/conftest.py` (add `ledger_db` fixture)
- Test: `tests/test_ledger_schema.py`

**Interfaces:**
- Consumes: `pg_conn` (Task 1).
- Produces: `migrations/0002_canonical_ledger_shadow.sql`; the `ledger_db` fixture (a `pg_conn` with the migration applied).

- [ ] **Step 1: Write the failing schema tests**

Create `tests/test_ledger_schema.py`:

```python
import psycopg
import pytest


def _insert(conn, **kw):
    cols = ", ".join(kw)
    ph = ", ".join(["%s"] * len(kw))
    conn.execute(f"INSERT INTO canonical_facts ({cols}) VALUES ({ph})", list(kw.values()))


def _base(**over):
    row = dict(owner_user_id="u1", subject_type="user", subject_id="self",
               predicate="home_city", cardinality="single",
               value_json='{"city": "Easton"}', normalized_value='{"city":"easton"}',
               status="active", scope="global")
    row.update(over)
    return row


def test_tables_exist(ledger_db):
    for t in ("canonical_facts", "canonical_fact_events"):
        n = ledger_db.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0]
        assert n == t


def test_single_slot_rejects_second_active(ledger_db):
    _insert(ledger_db, **_base())
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert(ledger_db, **_base(normalized_value='{"city":"reading"}'))


def test_single_slot_allows_second_when_first_superseded(ledger_db):
    _insert(ledger_db, id="11111111-1111-1111-1111-111111111111", **_base())
    ledger_db.execute("UPDATE canonical_facts SET status='superseded' WHERE status='active'")
    _insert(ledger_db, **_base(normalized_value='{"city":"reading"}'))  # no error


def test_multi_distinct_entities_coexist_but_dup_rejected(ledger_db):
    m = dict(predicate="children", cardinality="multi")
    _insert(ledger_db, **_base(sub_key="emma", value_json='{"name":"Emma"}',
                               normalized_value='{"name":"emma"}', **m))
    _insert(ledger_db, **_base(sub_key="liam", value_json='{"name":"Liam"}',
                               normalized_value='{"name":"liam"}', **m))  # distinct ok
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert(ledger_db, **_base(sub_key="emma", value_json='{"name":"Emma R"}',
                                   normalized_value='{"name":"emma r"}', **m))


def test_unknown_dedups_on_value_not_slot(ledger_db):
    u = dict(predicate="friend", cardinality="unknown", sub_key=None)
    _insert(ledger_db, **_base(value_json='{"name":"Sue"}', normalized_value='{"name":"sue"}', **u))
    _insert(ledger_db, **_base(value_json='{"name":"Mike"}', normalized_value='{"name":"mike"}', **u))  # ok
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert(ledger_db, **_base(value_json='{"name":"Sue"}', normalized_value='{"name":"sue"}', **u))


def test_idempotency_key_blocks_same_candidate_replay(ledger_db):
    kw = dict(source_exchange_id="ex1", extractor_version="v1")
    _insert(ledger_db, **_base(status="superseded", **kw))
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert(ledger_db, **_base(status="superseded", **kw))  # same idempotency key
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_ledger_schema.py -q`
Expected: FAIL (`fixture 'ledger_db' not found`).

- [ ] **Step 3: Write the migration (tables + indexes)**

Create `migrations/0002_canonical_ledger_shadow.sql`:

```sql
-- Canonical ledger — shadow-mode persistence (Stage 2).
--
-- Run ONCE in the Supabase SQL Editor (Dashboard -> SQL Editor). Additive and
-- idempotent — safe to re-run. NOTE: DATABASE_URL points at the Replit Postgres,
-- NOT Supabase, so this cannot be applied via that connection.
--
-- Creates the versioned fact ledger + its append-only event log, the three
-- per-cardinality partial unique indexes (the DB mirror of the predicate
-- registry), and the apply_canonical_delta RPC (a dumb, race-safe applicator of
-- a precomputed engine delta). No user-facing reads in this phase.

CREATE TABLE IF NOT EXISTS canonical_facts (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id       text NOT NULL,
    subject_type        text NOT NULL DEFAULT 'user',
    subject_id          text NOT NULL DEFAULT 'self',
    predicate           text NOT NULL,
    cardinality         text NOT NULL,              -- single | multi | unknown (snapshotted)
    value_json          jsonb NOT NULL,
    normalized_value    text NOT NULL,
    sub_key             text,
    status              text NOT NULL DEFAULT 'active',   -- active|superseded|deleted|expired|unconfirmed
    scope               text NOT NULL DEFAULT 'global',
    companion_id        text,
    valid_from          date,
    valid_until         date,
    observed_at         date,
    supersedes_fact_id  uuid,
    confirmation_status text NOT NULL DEFAULT 'inferred',
    sensitivity         text NOT NULL DEFAULT 'none',
    version             integer NOT NULL DEFAULT 1,
    extractor_version   text,
    mapper_version      text,
    engine_version      text,
    registry_version    text,
    decision_reason     text,
    source_exchange_id  text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

-- Three partial unique indexes — the DB mirror of predicate cardinality.
CREATE UNIQUE INDEX IF NOT EXISTS one_active_single ON canonical_facts
  (owner_user_id, subject_type, subject_id, predicate, scope,
   COALESCE(companion_id, ''), COALESCE(sub_key, ''))
  WHERE status = 'active' AND cardinality = 'single';

CREATE UNIQUE INDEX IF NOT EXISTS one_active_multi ON canonical_facts
  (owner_user_id, subject_type, subject_id, predicate, scope,
   COALESCE(companion_id, ''), sub_key)
  WHERE status = 'active' AND cardinality = 'multi';

CREATE UNIQUE INDEX IF NOT EXISTS one_active_unknown ON canonical_facts
  (owner_user_id, subject_type, subject_id, predicate, scope,
   COALESCE(companion_id, ''), normalized_value)
  WHERE status = 'active' AND cardinality = 'unknown';

-- Slot-load index.
CREATE INDEX IF NOT EXISTS canonical_facts_load_idx ON canonical_facts
  (owner_user_id, subject_type, subject_id, predicate, scope, companion_id, status);

-- Idempotency: the same candidate from the same turn cannot be double-inserted.
CREATE UNIQUE INDEX IF NOT EXISTS canonical_facts_idempotency_key ON canonical_facts
  (owner_user_id, source_exchange_id, predicate, scope,
   COALESCE(companion_id, ''), normalized_value, extractor_version);

CREATE INDEX IF NOT EXISTS canonical_facts_supersedes_idx ON canonical_facts (supersedes_fact_id);

CREATE TABLE IF NOT EXISTS canonical_fact_events (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id      text,
    source_exchange_id text,
    candidate_id       text,
    event_type         text NOT NULL,
    fact_id            uuid,
    related_fact_id    uuid,
    predicate          text,
    engine_version     text,
    mapper_version     text,
    extractor_version  text,
    registry_version   text,
    decision_reason    text,
    payload_json       jsonb NOT NULL DEFAULT '{}',
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS canonical_fact_events_exchange_idx
  ON canonical_fact_events (owner_user_id, source_exchange_id);
```

- [ ] **Step 4: Add the `ledger_db` fixture**

In `tests/conftest.py`, add at the end:

```python
import pathlib

_MIGRATION = pathlib.Path(__file__).parent.parent / "migrations" / "0002_canonical_ledger_shadow.sql"


@pytest.fixture
def ledger_db(pg_conn):
    pg_conn.execute(_MIGRATION.read_text())
    return pg_conn
```

- [ ] **Step 5: Run schema tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_ledger_schema.py -q`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add migrations/0002_canonical_ledger_shadow.sql tests/conftest.py tests/test_ledger_schema.py
git commit -m "feat(ledger): canonical_facts + events schema with per-cardinality unique indexes"
```

---

### Task 3: `apply_canonical_delta` RPC — inserts, events, idempotency, atomicity

**Files:**
- Modify: `migrations/0002_canonical_ledger_shadow.sql` (append the function)
- Test: `tests/test_apply_canonical_delta.py`

**Interfaces:**
- Produces: `apply_canonical_delta(p_supersedes jsonb, p_updates jsonb, p_inserts jsonb, p_events jsonb) RETURNS jsonb`. This task implements the insert + event + idempotency + atomicity behavior; Task 4 adds supersede/update CAS.

- [ ] **Step 1: Write the failing RPC tests**

Create `tests/test_apply_canonical_delta.py`:

```python
import json
import psycopg
import pytest


def _call(conn, *, supersedes=None, updates=None, inserts=None, events=None):
    return conn.execute(
        "SELECT apply_canonical_delta(%s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)",
        [json.dumps(supersedes or []), json.dumps(updates or []),
         json.dumps(inserts or []), json.dumps(events or [])],
    ).fetchone()[0]


def _fact(**over):
    f = dict(owner_user_id="u1", predicate="home_city", cardinality="single",
             value_json={"city": "Easton"}, normalized_value='{"city":"easton"}',
             status="active", scope="global", confirmation_status="inferred",
             source_exchange_id="ex1", extractor_version="v1")
    f.update(over)
    return f


def _count(conn, table="canonical_facts"):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_insert_creates_fact_and_event(ledger_db):
    _call(ledger_db,
          inserts=[_fact()],
          events=[{"owner_user_id": "u1", "source_exchange_id": "ex1",
                   "event_type": "fact_created", "predicate": "home_city",
                   "payload": {"normalized_value": '{"city":"easton"}'}}])
    assert _count(ledger_db) == 1
    assert _count(ledger_db, "canonical_fact_events") == 1
    row = ledger_db.execute("SELECT value_json->>'city', version FROM canonical_facts").fetchone()
    assert row[0] == "Easton" and row[1] == 1


def test_idempotent_replay_inserts_no_duplicate(ledger_db):
    ins = [_fact()]
    _call(ledger_db, inserts=ins)
    _call(ledger_db, inserts=ins)  # same source_exchange_id + normalized_value + extractor_version
    assert _count(ledger_db) == 1


def test_events_roll_back_with_a_failed_insert(ledger_db):
    # Two inserts into the SAME active single slot within one call: the second
    # violates one_active_single, aborting the whole call — no fact, no event.
    with pytest.raises(psycopg.errors.UniqueViolation):
        _call(ledger_db,
              inserts=[_fact(source_exchange_id="a"),
                       _fact(source_exchange_id="b", normalized_value='{"city":"reading"}',
                             value_json={"city": "Reading"})],
              events=[{"owner_user_id": "u1", "event_type": "fact_created"}])
    assert _count(ledger_db) == 0
    assert _count(ledger_db, "canonical_fact_events") == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_apply_canonical_delta.py -q`
Expected: FAIL (`function apply_canonical_delta(...) does not exist`).

- [ ] **Step 3: Append the RPC to the migration**

Append to `migrations/0002_canonical_ledger_shadow.sql`:

```sql
CREATE OR REPLACE FUNCTION apply_canonical_delta(
    p_supersedes jsonb DEFAULT '[]',
    p_updates    jsonb DEFAULT '[]',
    p_inserts    jsonb DEFAULT '[]',
    p_events     jsonb DEFAULT '[]'
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    ins jsonb;
    ev  jsonb;
    inserted integer := 0;
    n integer;
BEGIN
    -- (Task 4 will add supersede/update handling BEFORE this insert block.)

    -- Inserts: idempotent on the candidate identity; the partial unique indexes
    -- enforce one active row per slot.
    FOR ins IN SELECT * FROM jsonb_array_elements(p_inserts) LOOP
        INSERT INTO canonical_facts (
            id, owner_user_id, subject_type, subject_id, predicate, cardinality,
            value_json, normalized_value, sub_key, status, scope, companion_id,
            valid_from, valid_until, observed_at, supersedes_fact_id,
            confirmation_status, sensitivity, version, extractor_version,
            mapper_version, engine_version, registry_version, decision_reason,
            source_exchange_id)
        VALUES (
            COALESCE(NULLIF(ins->>'id','')::uuid, gen_random_uuid()),
            ins->>'owner_user_id',
            COALESCE(ins->>'subject_type','user'),
            COALESCE(ins->>'subject_id','self'),
            ins->>'predicate', ins->>'cardinality',
            ins->'value_json', ins->>'normalized_value', ins->>'sub_key',
            COALESCE(ins->>'status','active'), COALESCE(ins->>'scope','global'),
            ins->>'companion_id',
            NULLIF(ins->>'valid_from','')::date,
            NULLIF(ins->>'valid_until','')::date,
            NULLIF(ins->>'observed_at','')::date,
            NULLIF(ins->>'supersedes_fact_id','')::uuid,
            COALESCE(ins->>'confirmation_status','inferred'),
            COALESCE(ins->>'sensitivity','none'),
            COALESCE((ins->>'version')::int, 1),
            ins->>'extractor_version', ins->>'mapper_version', ins->>'engine_version',
            ins->>'registry_version', ins->>'decision_reason', ins->>'source_exchange_id')
        ON CONFLICT (owner_user_id, source_exchange_id, predicate, scope,
                     COALESCE(companion_id, ''), normalized_value, extractor_version)
        DO NOTHING;
        GET DIAGNOSTICS n = ROW_COUNT;
        inserted := inserted + n;
    END LOOP;

    -- Events: appended in the SAME transaction as the delta.
    FOR ev IN SELECT * FROM jsonb_array_elements(p_events) LOOP
        INSERT INTO canonical_fact_events (
            owner_user_id, source_exchange_id, candidate_id, event_type, fact_id,
            related_fact_id, predicate, engine_version, mapper_version,
            extractor_version, registry_version, decision_reason, payload_json)
        VALUES (
            ev->>'owner_user_id', ev->>'source_exchange_id', ev->>'candidate_id',
            ev->>'event_type', NULLIF(ev->>'fact_id','')::uuid,
            NULLIF(ev->>'related_fact_id','')::uuid, ev->>'predicate',
            ev->>'engine_version', ev->>'mapper_version', ev->>'extractor_version',
            ev->>'registry_version', ev->>'decision_reason',
            COALESCE(ev->'payload', ev->'payload_json', '{}'::jsonb));
    END LOOP;

    RETURN jsonb_build_object('ok', true, 'inserted', inserted);
END;
$$;
```

- [ ] **Step 4: Run RPC tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_apply_canonical_delta.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add migrations/0002_canonical_ledger_shadow.sql tests/test_apply_canonical_delta.py
git commit -m "feat(ledger): apply_canonical_delta RPC — inserts, events, idempotency, atomicity"
```

---

### Task 4: RPC — supersede/update with CAS, ordering, conflict rollback

**Files:**
- Modify: `migrations/0002_canonical_ledger_shadow.sql` (add supersede/update block before inserts)
- Test: `tests/test_apply_canonical_delta.py` (add cases)

**Interfaces:**
- Consumes: the RPC + `_call`/`_fact` helpers (Task 3).
- Produces: supersede/update CAS in `apply_canonical_delta`; a stale `expected_version` raises SQLSTATE `40001` and rolls the whole call back.

- [ ] **Step 1: Write the failing CAS tests**

Add to `tests/test_apply_canonical_delta.py`:

```python
def _one_active(conn):
    return conn.execute(
        "SELECT id, version, value_json->>'city' FROM canonical_facts "
        "WHERE status='active'").fetchall()


def test_supersede_then_insert_moves_the_slot(ledger_db):
    ins = _fact(id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    _call(ledger_db, inserts=[ins])
    # Now supersede the old and insert the new (Easton -> Reading), one call.
    _call(ledger_db,
          supersedes=[{"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                       "expected_version": 1, "new_status": "superseded"}],
          inserts=[_fact(source_exchange_id="ex2", value_json={"city": "Reading"},
                         normalized_value='{"city":"reading"}',
                         supersedes_fact_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")])
    active = _one_active(ledger_db)
    assert len(active) == 1 and active[0][2] == "Reading"


def test_stale_version_supersede_raises_and_rolls_back(ledger_db):
    ins = _fact(id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    _call(ledger_db, inserts=[ins])
    with pytest.raises(psycopg.errors.SerializationFailure):
        _call(ledger_db,
              supersedes=[{"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                           "expected_version": 99, "new_status": "superseded"}],
              inserts=[_fact(source_exchange_id="ex3", value_json={"city": "Reading"},
                             normalized_value='{"city":"reading"}')])
    # Nothing changed: old fact still active v1, the new insert did not land.
    active = _one_active(ledger_db)
    assert len(active) == 1 and active[0][1] == 1 and active[0][2] == "Easton"


def test_update_confirmation_bumps_version_via_cas(ledger_db):
    ins = _fact(id="cccccccc-cccc-cccc-cccc-cccccccccccc")
    _call(ledger_db, inserts=[ins])
    _call(ledger_db, updates=[{"id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                               "expected_version": 1,
                               "confirmation_status": "user_confirmed"}])
    row = ledger_db.execute(
        "SELECT confirmation_status, version FROM canonical_facts").fetchone()
    assert row[0] == "user_confirmed" and row[1] == 2


def test_stale_update_raises(ledger_db):
    ins = _fact(id="dddddddd-dddd-dddd-dddd-dddddddddddd")
    _call(ledger_db, inserts=[ins])
    with pytest.raises(psycopg.errors.SerializationFailure):
        _call(ledger_db, updates=[{"id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                                   "expected_version": 5,
                                   "confirmation_status": "user_confirmed"}])
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `./venv/bin/python -m pytest tests/test_apply_canonical_delta.py -q`
Expected: FAIL (supersedes/updates are ignored today — `test_supersede_then_insert_moves_the_slot` leaves two active rows → `one_active_single` violation or wrong active count; stale-version tests don't raise).

- [ ] **Step 3: Add the supersede/update block to the RPC**

In `migrations/0002_canonical_ledger_shadow.sql`, replace the line
`    -- (Task 4 will add supersede/update handling BEFORE this insert block.)`
with:

```sql
    -- Supersedes/deletes FIRST (frees the active slot before inserts), under
    -- optimistic CAS: a mismatched expected_version means a concurrent writer
    -- moved the row — abort the whole call so the caller reloads and retries.
    FOR ins IN SELECT * FROM jsonb_array_elements(p_supersedes) LOOP
        UPDATE canonical_facts
           SET status      = COALESCE(ins->>'new_status', 'superseded'),
               valid_until = NULLIF(ins->>'valid_until','')::date,
               version     = version + 1,
               updated_at  = now()
         WHERE id = (ins->>'id')::uuid
           AND version = (ins->>'expected_version')::int;
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n = 0 THEN
            RAISE EXCEPTION 'cas_conflict superseding fact %', ins->>'id'
                USING ERRCODE = '40001';
        END IF;
    END LOOP;

    -- Updates (confirmations/corrections): CAS field update, no status change.
    FOR ins IN SELECT * FROM jsonb_array_elements(p_updates) LOOP
        UPDATE canonical_facts
           SET confirmation_status = ins->>'confirmation_status',
               version    = version + 1,
               updated_at = now()
         WHERE id = (ins->>'id')::uuid
           AND version = (ins->>'expected_version')::int;
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n = 0 THEN
            RAISE EXCEPTION 'cas_conflict updating fact %', ins->>'id'
                USING ERRCODE = '40001';
        END IF;
    END LOOP;
```

(The `ins` loop variable is reused; it is already declared. The block sits between the `BEGIN` and the insert `FOR` loop.)

- [ ] **Step 4: Run all RPC tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_apply_canonical_delta.py -q`
Expected: PASS (7 passed — 3 from Task 3 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add migrations/0002_canonical_ledger_shadow.sql tests/test_apply_canonical_delta.py
git commit -m "feat(ledger): RPC supersede/update CAS with conflict rollback + slot ordering"
```

---

### Task 5: Full-suite green gate + finish

**Files:** none (verification + branch finish).

- [ ] **Step 1: Run the entire suite**

Run: `./venv/bin/python -m pytest tests/ -q && ./venv/bin/python -m benchmark.runner`
Expected: all pass (pure Stage-1 tests + the new pg-backed tests); benchmark still `A1: 13/13 scenarios passed. Hard gates: clean.`

- [ ] **Step 2: Confirm the migration is self-contained + idempotent**

Run: `./venv/bin/python -c "import psycopg" && echo "driver ok"` and re-run the schema test twice to prove idempotency:
`./venv/bin/python -m pytest tests/test_ledger_schema.py tests/test_apply_canonical_delta.py -q`
Expected: green both times (the `IF NOT EXISTS` / `CREATE OR REPLACE` migration re-applies cleanly).

- [ ] **Step 3: Confirm scope**

Run: `git diff --name-only origin/main...HEAD | grep -vE '^artifacts/voice-companion/(migrations/|tests/|requirements-dev.txt|docs/)'` — expect no output (only migrations/tests/requirements/docs changed; no app runtime code).

- [ ] **Step 4: Finish the branch**

Announce and use **superpowers:finishing-a-development-branch** to verify tests, then merge/PR, reporting the proven result. Note in the finish summary: **the migration must be hand-applied in the Supabase SQL Editor** (`migrations/0002_canonical_ledger_shadow.sql`) — the ledger is still inert (no repository/wiring yet; Stage 3), so no Republish is required for safety.

---

## Roadmap — remaining shadow-mode plans (after this)

3. **Live wiring** — `repository.py` (PostgREST load + `apply_canonical_delta` call with retry-on-`40001`); nested-`canonical` prompt behind the A/B gate; `LegacyOutcome` refactor; per-turn `exchange_id`; always-run `shadow_ledger.run` with timeout + gating. Carries forward the Stage-1 note: align `subject_id` default (`self`).
4. **Observability** — `ledger_shadow_divergences` + `ledger_shadow_runs` tables (deferred here), receipts, divergence classifier, daily rollup + agreement sample, admin endpoint.
5. **Privacy & lifecycle** — retention, `delete_account` extension, sensitive-payload metadata-only.
```
