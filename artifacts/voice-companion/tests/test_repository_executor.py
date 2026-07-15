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
