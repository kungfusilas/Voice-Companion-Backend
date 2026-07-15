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


def test_multi_null_sub_key_slot_still_dedups(ledger_db):
    m = dict(predicate="children", cardinality="multi", sub_key=None)
    _insert(ledger_db, **_base(value_json='{"n":1}', normalized_value='{"n":1}', **m))
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert(ledger_db, **_base(value_json='{"n":2}', normalized_value='{"n":2}', **m))


def test_invalid_cardinality_rejected(ledger_db):
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert(ledger_db, **_base(cardinality="bogus"))
