import asyncio
import json

import pytest

from app.canonical.repository import PostgrestExecutor, ConflictError


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)
    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self._resp
    async def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self._resp


def _ex(resp):
    fake = _FakeClient(resp)
    return PostgrestExecutor("https://x.supabase.co", "key",
                             client_factory=lambda: fake), fake


def test_fetch_builds_filtered_get():
    ex, fake = _ex(_FakeResp(200, [{"id": "a", "value_json": {"city": "Easton"}}]))
    rows = asyncio.run(ex.fetch_active_facts("u1", "user", "self", "home_city", "global", None))
    assert rows[0]["id"] == "a"
    method, url, kw = fake.calls[0]
    assert method == "GET" and "/rest/v1/canonical_facts" in url
    assert kw["params"]["owner_user_id"] == "eq.u1" and kw["params"]["status"] == "eq.active"
    assert kw["params"]["companion_id"] == "is.null"
    assert kw["params"]["select"] == "*"


def test_apply_posts_rpc_and_returns_body():
    ex, fake = _ex(_FakeResp(200, {"ok": True, "inserted": 1}))
    res = asyncio.run(ex.apply_delta([], [], [{"predicate": "home_city"}], []))
    method, url, kw = fake.calls[0]
    assert method == "POST" and url.endswith("/rest/v1/rpc/apply_canonical_delta")
    assert kw["json"]["p_inserts"] == [{"predicate": "home_city"}]
    assert res["inserted"] == 1
    assert kw["json"]["p_supersedes"] == [] and kw["json"]["p_updates"] == []
    assert kw["json"]["p_events"] == []


@pytest.mark.parametrize("code", ["40001", "23505"])
def test_conflict_sqlstate_maps_to_conflicterror(code):
    ex, _ = _ex(_FakeResp(400, {"code": code, "message": "conflict"}))
    with pytest.raises(ConflictError):
        asyncio.run(ex.apply_delta([{"id": "x", "expected_version": 1}], [], [], []))


def test_non_conflict_error_raises_runtimeerror():
    ex, _ = _ex(_FakeResp(500, {"code": "42P01", "message": "undefined_table"}))
    with pytest.raises(RuntimeError):
        asyncio.run(ex.apply_delta([], [], [{"predicate": "x"}], []))


def test_fetch_error_maps_to_conflicterror():
    ex, _ = _ex(_FakeResp(400, {"code": "40001", "message": "conflict"}))
    with pytest.raises(ConflictError):
        asyncio.run(ex.fetch_active_facts("u1", "user", "self", "home_city", "global", None))


def test_fetch_non_conflict_error_raises_runtimeerror():
    ex, _ = _ex(_FakeResp(500, {"code": "42P01", "message": "undefined_table"}))
    with pytest.raises(RuntimeError):
        asyncio.run(ex.fetch_active_facts("u1", "user", "self", "home_city", "global", None))
