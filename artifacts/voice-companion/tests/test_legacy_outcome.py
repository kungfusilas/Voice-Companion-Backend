import asyncio
import json
from app import memory_extractor
from app.memory_extractor import LegacyOutcome


def _fake_llm(monkeypatch, payload):
    async def fake_send(*a, **kw):
        return json.dumps(payload)
    monkeypatch.setattr(memory_extractor.claude, "send_message", fake_send)


def _fake_supabase(monkeypatch, existing=None):
    # Make the httpx Supabase round-trips no-ops that report no existing facts.
    import httpx

    class _Resp:
        status_code = 200
        def json(self):
            return existing or []

    class _Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, *a, **kw):
            return _Resp()
        async def post(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _Client())
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "key")


def test_returns_outcome_with_parsed_facts_including_canonical(monkeypatch):
    _fake_llm(monkeypatch, [
        {"category": "location", "fact": "Lives in Easton", "sensitivity": "none",
         "canonical": {"subject_type": "user", "predicate": "home_city",
                       "value_json": {"city": "Easton"}}}])
    _fake_supabase(monkeypatch)
    out = asyncio.run(memory_extractor.extract_and_save_core_facts("u1", "msg", "reply"))
    assert isinstance(out, LegacyOutcome)
    assert len(out.facts) == 1
    assert out.facts[0]["fact"] == "Lives in Easton"
    assert out.facts[0]["canonical"]["predicate"] == "home_city"


def test_returns_empty_outcome_on_no_facts(monkeypatch):
    _fake_llm(monkeypatch, [])
    _fake_supabase(monkeypatch)
    out = asyncio.run(memory_extractor.extract_and_save_core_facts("u1", "msg", "reply"))
    assert out.status == "empty" and out.facts == []


def test_never_raises_returns_error_outcome(monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("llm down")
    monkeypatch.setattr(memory_extractor.claude, "send_message", boom)
    out = asyncio.run(memory_extractor.extract_and_save_core_facts("u1", "msg", "reply"))
    assert out.status == "error" and out.facts == []


def test_post_parse_error_still_returns_facts(monkeypatch):
    _fake_llm(monkeypatch, [{"category": "location", "fact": "Lives in Easton",
                             "sensitivity": "none"}])
    import httpx

    class _BoomClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, *a, **kw):
            raise RuntimeError("supabase down")

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _BoomClient())
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "key")
    out = asyncio.run(memory_extractor.extract_and_save_core_facts("u1", "m", "r"))
    assert out.status == "error"
    assert len(out.facts) == 1
