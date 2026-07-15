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


def _one_active(conn):
    return conn.execute(
        "SELECT id, version, value_json->>'city' FROM canonical_facts "
        "WHERE status='active'").fetchall()


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


def test_replay_does_not_duplicate_events(ledger_db):
    ins = [_fact()]
    ev = [{"owner_user_id": "u1", "source_exchange_id": "ex1",
           "event_type": "fact_created", "predicate": "home_city"}]
    _call(ledger_db, inserts=ins, events=ev)
    _call(ledger_db, inserts=ins, events=ev)  # replay: insert no-ops, events must not duplicate
    assert _count(ledger_db) == 1
    assert _count(ledger_db, "canonical_fact_events") == 1


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
