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
