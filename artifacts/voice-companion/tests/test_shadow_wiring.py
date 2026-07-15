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
        return LegacyOutcome("inserted", [{"fact": "x", "sensitivity": "none"}])

    async def fake_run(outcome, **kw):
        calls.append(("shadow", kw["exchange_id"], len(outcome.facts)))
        return {"applied": 0}

    monkeypatch.setattr(chat.memory_extractor, "extract_and_save_core_facts", fake_extract)
    monkeypatch.setattr(chat.shadow_ledger, "run", fake_run)

    asyncio.run(chat._extract_and_shadow("u1", "msg", "reply", "exABC"))
    assert calls[0] == "legacy"                       # legacy first
    assert calls[1] == ("shadow", "exABC", 1)         # shadow after, same exchange id


def test_extract_and_shadow_never_raises(monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("down")
    monkeypatch.setattr(chat.memory_extractor, "extract_and_save_core_facts", boom)
    asyncio.run(chat._extract_and_shadow("u1", "msg", "reply", "exABC"))  # must not raise


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
