from datetime import date
from app.canonical.engine import apply_candidate
from app.canonical.delta import compute_delta
from app.canonical.models import Candidate, Fact


def _home(city, conf="explicitly_stated", vf=None):
    return Candidate(subject_type="user", predicate="home_city",
                     value_json={"city": city}, confirmation_status=conf, valid_from=vf)


def _active_home(city, version=1):
    from app.canonical.engine import normalize_value
    return Fact(id=f"id-{city}", subject_type="user", subject_id="self",
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


def test_historical_candidate_is_insert_only_with_candidate_unconfirmed_event():
    from app.canonical.engine import normalize_value
    now = date(2027, 6, 1)
    before = [Fact(id="cur", subject_type="user", subject_id="self", predicate="home_city",
                   value_json={"city": "Easton"},
                   normalized_value=normalize_value({"city": "Easton"}),
                   version=2, cardinality="single", valid_from=date(2027, 1, 1))]
    cand = Candidate(subject_type="user", predicate="home_city", value_json={"city": "Reading"},
                     confirmation_status="explicitly_stated", valid_from=date(2026, 1, 1))
    after = apply_candidate(before, cand, now)
    d = compute_delta(before, after, engine_version="v1")
    # historical (older valid_from) candidate → recorded as a superseded insert; current fact untouched → no CAS op
    assert len(d.inserts) == 1 and d.inserts[0].status == "superseded"
    assert not d.supersedes
    assert any(e["event_type"] == "candidate_unconfirmed" for e in d.events)


def test_delete_status_change_emits_fact_deleted():
    from app.canonical.engine import apply_control, normalize_value
    from app.canonical.models import Control
    now = date(2027, 6, 1)
    before = [Fact(id="cur", subject_type="user", subject_id="self", predicate="home_city",
                   value_json={"city": "Easton"},
                   normalized_value=normalize_value({"city": "Easton"}),
                   version=1, cardinality="single", status="active")]
    after, _ = apply_control(before, Control(op="forget", key="user.home_city"), now)
    d = compute_delta(before, after, engine_version="v1")
    assert len(d.supersedes) == 1 and d.supersedes[0]["new_status"] == "deleted"
    assert any(e["event_type"] == "fact_deleted" for e in d.events)


def test_confirm_produces_update_op_not_dedup():
    from app.canonical.engine import apply_control, normalize_value
    from app.canonical.models import Control
    now = date(2027, 6, 1)
    before = [Fact(id="cur", subject_type="user", subject_id="self", predicate="home_city",
                   value_json={"city": "Easton"},
                   normalized_value=normalize_value({"city": "Easton"}),
                   version=1, cardinality="single", status="active",
                   confirmation_status="inferred")]
    after, _ = apply_control(before, Control(op="confirm", key="user.home_city"), now)
    d = compute_delta(before, after, engine_version="v1")
    assert not d.is_empty()
    assert len(d.updates) == 1
    assert d.updates[0] == {"id": "cur", "expected_version": 1, "confirmation_status": "user_confirmed"}
    kinds = [e["event_type"] for e in d.events]
    assert "fact_confirmed" in kinds and "fact_deduped" not in kinds
