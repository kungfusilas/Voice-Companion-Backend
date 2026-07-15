import asyncio
import pathlib
from datetime import date

from app.canonical.repository import (PsycopgExecutor, ConflictError, LedgerContext,
                                      row_to_fact, fact_to_insert, enrich_event)
from app.canonical.models import Fact

_MIG = pathlib.Path(__file__).parent.parent / "migrations" / "0002_canonical_ledger_shadow.sql"


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
             cardinality="single", valid_from=date(2026, 6, 1),
             valid_until=date(2026, 12, 31), observed_at=date(2026, 7, 1))
    d = fact_to_insert(f, _ctx())
    assert d["owner_user_id"] == "u1" and d["source_exchange_id"] == "ex1"
    assert d["extractor_version"] == "v1" and d["engine_version"]
    assert d["valid_from"] == "2026-06-01"
    assert d["valid_until"] == "2026-12-31" and d["observed_at"] == "2026-07-01"
    assert d["value_json"] == {"city": "Easton"}


def test_enrich_event_injects_owner_and_exchange():
    ev = enrich_event({"event_type": "fact_created", "fact_id": "x"}, _ctx())
    assert ev["owner_user_id"] == "u1" and ev["source_exchange_id"] == "ex1"
    assert ev["event_type"] == "fact_created"


def test_as_date_normalizes_datetime():
    from datetime import datetime
    from app.canonical.repository import _as_date, _iso
    assert _as_date(datetime(2026, 7, 1, 13, 30)) == date(2026, 7, 1)
    assert _iso(datetime(2026, 7, 1, 13, 30)) == "2026-07-01"


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
