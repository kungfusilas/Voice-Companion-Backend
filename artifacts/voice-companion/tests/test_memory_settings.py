from datetime import datetime, timedelta, timezone

from app.memory_settings import should_collect


def test_collects_when_no_settings():
    assert should_collect({}, "financial") is True


def test_blocks_disabled_sensitivity():
    s = {"disabled_sensitivities": ["financial", "sexual"]}
    assert should_collect(s, "financial") is False
    assert should_collect(s, "health") is True


def test_paused_blocks_everything():
    s = {"collection_paused": True}
    assert should_collect(s, "none") is False


def test_pause_expires():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    s = {"collection_paused": True, "paused_until": past}
    assert should_collect(s, "none") is True  # window elapsed → collect


def test_pause_still_active():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    s = {"collection_paused": True, "paused_until": future}
    assert should_collect(s, "none") is False


def test_unparseable_paused_until_treated_as_paused():
    s = {"collection_paused": True, "paused_until": "not-a-date"}
    assert should_collect(s, "none") is False
