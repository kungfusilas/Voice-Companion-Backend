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
