"""
Application-composition regression tests for app.main.

The 2026-07-12 regression (commit 2c21f00) removed app.routers.tts from
main.py's imports and app.include_router calls. routers/tts.py's own logic
was — and remained — completely correct; nothing in tests/test_*.py caught
the break because nothing exercised the *composed* app. These tests import
the real app.main:app and assert on it directly, so a future accidental
removal of a router registration fails a test instead of shipping silently.

TestClient is deliberately NOT used as a context manager: Starlette only
runs FastAPI's lifespan (which starts the APScheduler background jobs) when
TestClient is entered via `with`. A bare TestClient(app) never triggers
startup/shutdown, so no scheduled job, Supabase write, or OpenAI request can
fire from this file. Personas are seeded directly (mirroring only the
side-effect-free half of lifespan); auth, voice quota, and OpenAI synthesis
are mocked.
"""
import os
from unittest.mock import AsyncMock

import pytest

# app.main transitively imports app.session_debrief, which reads these three
# vars at module load time (unrelated to TTS) — no network call is made from
# reading them. Matches the same setdefault pattern already used in
# tests/test_shadow_wiring.py.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from fastapi.testclient import TestClient

from app.main import app
from app.auth_middleware import verify_token
from app.companions import COMPANIONS, build_system_prompt
from app import store
import app.routers.tts as tts_router

TEST_USER_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def _seed_personas():
    # Mirrors only the pure, in-memory persona-seeding half of app.main's
    # lifespan. Never starts the scheduler and never touches Supabase/OpenAI.
    for companion in COMPANIONS:
        companion.system_prompt_override = build_system_prompt(companion)
        store.create_persona(companion)
    yield


@pytest.fixture
def client():
    # No `with` block on purpose — see module docstring.
    return TestClient(app)


def test_tts_routes_are_registered_on_the_composed_app():
    """The exact class of regression this guards against: routers/tts.py
    can be perfectly correct and still be unreachable in production if
    app.main never mounts it. Assert against the composed app's resolved
    OpenAPI schema (not raw app.routes, whose internal representation of
    included routers is FastAPI-version-dependent) so this stays accurate
    across FastAPI versions."""
    schema_paths = app.openapi()["paths"]
    assert "post" in schema_paths.get("/api/tts/speak", {})
    assert "post" in schema_paths.get("/api/tts/speak/stream", {})


def test_post_tts_speak_reaches_the_real_handler(client, monkeypatch):
    """POST /api/tts/speak must be dispatched to routers/tts.py's real
    handler (not fall through to the SPA catch-all, which was the actual
    2026-07-12 production symptom: a 405 from the wildcard GET route).
    Auth, voice quota, and OpenAI synthesis are mocked; everything else —
    request validation, text sanitization, response headers — is real."""
    fake_audio = b"FAKE_MP3_BYTES"

    app.dependency_overrides[verify_token] = lambda: TEST_USER_ID
    get_user_tier_mock = AsyncMock(return_value=("power", "active"))
    check_voice_quota_mock = AsyncMock(return_value=None)
    synthesize_mock = AsyncMock(return_value=fake_audio)
    monkeypatch.setattr(tts_router, "get_user_tier", get_user_tier_mock)
    monkeypatch.setattr(tts_router, "check_voice_quota", check_voice_quota_mock)
    monkeypatch.setattr(tts_router.openai_tts_client, "synthesize", synthesize_mock)

    try:
        resp = client.post(
            "/api/tts/speak",
            json={"text": "Hello from a regression test.", "persona_id": "companion-aeva"},
        )
    finally:
        app.dependency_overrides.pop(verify_token, None)

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == fake_audio
    # The success path never sets X-Voice-Available — that header only
    # appears on the graceful-degrade failure path (routers/tts.py's
    # VOICE_UNAVAILABLE_HEADERS). Its absence here IS the success signal.
    assert "x-voice-available" not in resp.headers

    synthesize_mock.assert_called_once()
    assert synthesize_mock.call_args.kwargs.get("voice") == "nova"  # companion-aeva's mapped voice
    check_voice_quota_mock.assert_called_once()
