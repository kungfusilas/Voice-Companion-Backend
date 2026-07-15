import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

import asyncio
from app.routers import chat


def test_extract_and_shadow_runs_shadow_after_legacy(monkeypatch):
    calls = []

    async def fake_extract(user_id, msg, reply):
        calls.append("legacy")
        from app.memory_extractor import LegacyOutcome
        return LegacyOutcome("inserted", [{"fact": "x", "sensitivity": "none",
                                           "canonical": {"predicate": "home_city",
                                                         "value_json": {"city": "X"}}}])

    async def fake_run(outcome, **kw):
        calls.append(("shadow", kw["exchange_id"], len(outcome.facts)))
        return {"applied": 0}

    async def fake_settings(user_id):
        return {}

    monkeypatch.setattr(chat.memory_extractor, "extract_and_save_core_facts", fake_extract)
    monkeypatch.setattr(chat.shadow_ledger, "run", fake_run)
    monkeypatch.setattr(chat.memory_settings, "get_settings", fake_settings)

    asyncio.run(chat._extract_and_shadow("u1", "msg", "reply", "exABC"))
    assert calls[0] == "legacy"                       # legacy first
    assert calls[1] == ("shadow", "exABC", 1)         # shadow after, same exchange id


def test_extract_and_shadow_never_raises(monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("down")

    async def fake_settings(user_id):
        return {}
    monkeypatch.setattr(chat.memory_extractor, "extract_and_save_core_facts", boom)
    monkeypatch.setattr(chat.memory_settings, "get_settings", fake_settings)
    asyncio.run(chat._extract_and_shadow("u1", "msg", "reply", "exABC"))  # must not raise


def test_no_canonical_skips_settings_and_shadow(monkeypatch):
    settings_called, shadow_called = [], []

    async def fake_extract(user_id, msg, reply):
        from app.memory_extractor import LegacyOutcome
        return LegacyOutcome("inserted", [{"fact": "x", "sensitivity": "none"}])  # no canonical

    async def fake_settings(user_id):
        settings_called.append(1)
        return {}

    async def fake_run(outcome, **kw):
        shadow_called.append(1)
        return {}

    monkeypatch.setattr(chat.memory_extractor, "extract_and_save_core_facts", fake_extract)
    monkeypatch.setattr(chat.memory_settings, "get_settings", fake_settings)
    monkeypatch.setattr(chat.shadow_ledger, "run", fake_run)
    asyncio.run(chat._extract_and_shadow("u1", "msg", "reply", "exABC"))
    assert settings_called == [] and shadow_called == []   # zero DB, zero shadow when no canonical


def test_save_exchange_stamps_message_id(monkeypatch):
    from app import conversation_store
    captured = {}

    async def fake_rpc(client, user_id, companion_id, session_id, new_msgs):
        captured["msgs"] = new_msgs
        return True

    monkeypatch.setattr(conversation_store, "_save_via_rpc", fake_rpc)
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "key")
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _NoClient())

    asyncio.run(conversation_store.save_exchange("u1", "c1", "s1", "hi", "hello",
                                                 exchange_id="exABC"))
    ids = [m.get("id") for m in captured["msgs"]]
    assert ids == ["exABC:user", "exABC:assistant"]


class _NoClient:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
