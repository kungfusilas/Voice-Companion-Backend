from datetime import date
from app.canonical.engine import apply_candidate
from app.canonical.delta import compute_delta
from app.canonical.models import Candidate, Fact


def _home(city, conf="explicitly_stated", vf=None):
    return Candidate(subject_type="user", predicate="home_city",
                     value_json={"city": city}, confirmation_status=conf, valid_from=vf)


def _active_home(city, version=1):
    from app.canonical.engine import normalize_value
    return Fact(id=f"id-{city}", subject_type="user", subject_id="user",
                predicate="home_city", value_json={"city": city},
                normalized_value=normalize_value({"city": city}), version=version,
                cardinality="single")


def test_insert_only_when_no_prior():
    now = date(2027, 1, 1)
    before = []
    after = apply_candidate(before, _home("Easton"), now)
    d = compute_delta(before, after, engine_version="v1")
    assert len(d.inserts) == 1 and not d.supersedes
    assert any(e["event_type"] == "fact_created" for e in d.events)


def test_supersession_produces_insert_plus_conditional_supersede():
    now = date(2027, 2, 1)
    before = [_active_home("Bethlehem", version=3)]
    after = apply_candidate(before, _home("Easton"), now)
    d = compute_delta(before, after, engine_version="v1")
    assert len(d.inserts) == 1
    assert len(d.supersedes) == 1
    op = d.supersedes[0]
    assert op["id"] == "id-Bethlehem"
    assert op["expected_version"] == 3
    assert op["new_status"] == "superseded"
    kinds = {e["event_type"] for e in d.events}
    assert "fact_superseded" in kinds and "fact_created" in kinds


def test_dedup_is_empty_delta():
    now = date(2027, 1, 1)
    before = [_active_home("Easton")]
    after = apply_candidate(before, _home("Easton"), now)
    d = compute_delta(before, after, engine_version="v1")
    assert d.is_empty()
    assert [e["event_type"] for e in d.events] == ["fact_deduped"]
