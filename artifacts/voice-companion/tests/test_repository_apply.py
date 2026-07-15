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


def test_durable_multi_supersedes_within_entity_only(ledger_db):
    ex = PsycopgExecutor(ledger_db)

    def _child(name, age):
        return Candidate(subject_type="user", subject_id="self", predicate="children",
                         value_json={"name": name, "age": age},
                         confirmation_status="explicitly_stated")

    async def body():
        await apply_candidate_durably(ex, _child("Alice", 8), _ctx("c1"), now=date(2026, 1, 1))
        await apply_candidate_durably(ex, _child("Bob", 5), _ctx("c2"), now=date(2026, 1, 2))
        await apply_candidate_durably(ex, _child("Alice", 9), _ctx("c3"), now=date(2026, 2, 1))

    asyncio.run(body())
    rows = asyncio.run(ex.fetch_active_facts("u1", "user", "self", "children", "global", None))
    by_name = {r["value_json"]["name"]: r["value_json"]["age"] for r in rows}
    assert by_name == {"Alice": 9, "Bob": 5} and len(rows) == 2


def test_durable_unknown_accumulates_distinct_values(ledger_db):
    ex = PsycopgExecutor(ledger_db)

    def _friend(name):
        return Candidate(subject_type="user", subject_id="self", predicate="friend",
                         value_json={"name": name}, confirmation_status="explicitly_stated")

    async def body():
        await apply_candidate_durably(ex, _friend("Sue"), _ctx("f1"), now=date(2026, 1, 1))
        await apply_candidate_durably(ex, _friend("Mike"), _ctx("f2"), now=date(2026, 1, 2))
        await apply_candidate_durably(ex, _friend("Sue"), _ctx("f3"), now=date(2026, 1, 3))

    asyncio.run(body())
    rows = asyncio.run(ex.fetch_active_facts("u1", "user", "self", "friend", "global", None))
    names = sorted(r["value_json"]["name"] for r in rows)
    assert names == ["Mike", "Sue"] and len(rows) == 2
