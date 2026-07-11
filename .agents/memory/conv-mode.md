---
name: Always-on conversation mode
description: Architecture decisions for the hands-free voice conversation loop (paid tiers)
---

## Architecture

Browser mic (AudioWorklet PCM Int16) → FastAPI WS /api/stt/stream → Deepgram live WS → Deepgram transcript events → browser hook → chat pipeline → TTS → barge-in detection.

**Why AudioWorklet (not MediaRecorder):** MediaRecorder on Safari requires WebM→MP4 fallback and can't produce continuous streaming. AudioWorklet gives Float32→Int16 PCM that Deepgram's streaming API accepts at any sample rate. Works on Safari 14.5+.

**Why raw `websockets` (not Deepgram Python SDK streaming):** The Deepgram SDK's async live client adds complexity. A raw `websockets.connect()` with `additional_headers={"Authorization": f"Token {key}"}` is simpler and in websockets v15 this is the correct param (renamed from `extra_headers` in v12).

**Barge-in guard:** Only triggers if ≥3 words + confidence≥0.5 + transcript not a substring of `currentTtsTextRef.current`. The `currentTtsTextRef` is set in Chat.tsx's TTS block before playback and cleared in `finally`. `echoCancellation: true` in getUserMedia handles the hardware side.

**Billing:** Server-side per finalized utterance using Deepgram's `words[0].start` → `words[-1].end` duration. Idle listening is never billed.

**WebSocket auth:** JWT passed as `?token=<jwt>` query param (browsers can't set custom headers on WebSocket upgrade). Reuses existing JWKS verification via `_get_public_keys()` from `auth_middleware.py`.

**State machine:** off → listening → processing → speaking → listening (loop). Processing has a 25s safety timeout that falls back to listening if TTS never starts.

**Recovery must NOT depend only on `isPlaying` toggling.** The processing→speaking→listening transition is driven by the audio player's `isPlaying` flag. If TTS synthesis fails, no audio plays, `isPlaying` never toggles, and the loop stalls in "processing" until the 25s backstop — so every turn stalls ~25s while a provider (e.g. ElevenLabs) is failing, which users report as "voice completely broken, nothing sends." **Why:** the flag is only a proxy for "turn done." **How to apply:** `onTranscriptFinalized` is awaitable and returns `sendMessage`'s promise; on `.finally()`, if still "processing", force back to "listening" immediately. Keep the 25s timeout only as a network-hang backstop.

**TTS failures degrade to text-only, never hard errors.** `/tts/speak` returns HTTP 200 + empty body + header `X-Voice-Available: false` on ElevenLabs/OpenAI synth failure (was 502); stream generators log+`return` instead of raising. Frontend `useAudioPlayer.play()` no-ops on a 0-byte blob. Chat text always comes from the chat stream independently of TTS, so text shows regardless. **Why:** a TTS 5xx used to propagate as an ApiError and (via the stall above) freeze voice sending.

**TTS synthesis lives in `app/routers/tts.py`, NOT `chat.py`.** `chat.py` only flags whether voice is available; the actual ElevenLabs/OpenAI calls (`elevenlabs_client` / `openai_tts_client`, both streaming and non-streaming) are in `tts.py`. Any TTS-behavior change (timeouts, degradation) must go there — editing `chat.py` does nothing for voice output.

**TTS calls need hard `asyncio.wait_for` timeouts (ElevenLabs 12s, OpenAI 10s).** A stalled provider call can hang forever WITHOUT raising, so `try/except` alone never fires and the client freezes. **Why:** the observed "voice hang" was a silent ElevenLabs stall, not an exception. **How to apply:** wrap non-streaming `synthesize()` in `asyncio.wait_for`; for streaming, use a PER-CHUNK timeout on `it.__anext__()` (not a total-duration cap, which would truncate long-but-healthy audio). On `asyncio.TimeoutError`, degrade to text-only. Non-timeout exceptions must still propagate so the plain-text retry/degrade logic runs.

**Two chat endpoints; mobile uses the STREAMING one.** `chat.py` has `POST /chat` (non-streaming, returns `ChatResponse`) and `POST /chat/stream` (SSE). The frontend (`src/lib/api.ts`) calls `/chat/stream`. Any "chat endpoint" behavior change must target the streaming one to affect mobile.

**Global request timeout differs by endpoint shape.** Non-streaming `/chat` wraps its body (`_chat_impl`) in `asyncio.wait_for(..., 45)` → returns `JSONResponse(504, {"message":"Request timed out"})`; only `asyncio.TimeoutError` is caught so `HTTPException` (402/404) still propagates. Streaming `/chat/stream` CANNOT return a 504 status once SSE headers flush — instead an outer `event_generator` wraps the inner `_raw_event_generator`, enforces a 45s wall-clock deadline via per-`__anext__` `wait_for` against remaining budget, and on timeout emits a terminal SSE `{"type":"error","message":"Request timed out"}` event (frontend already handles `error` type) + `aclose()`. **Why:** silent LLM/network hangs froze the client. **Caveat:** the 45s is total wall-clock incl. client backpressure, so very slow clients can trip it — accepted as strict anti-hang.

**Diagnostic logging convention:** `[REQUEST] user=... endpoint=chat|chat_stream method=POST` at top of each chat handler; `[TTS] starting/done for user=...` around synthesis IN tts.py (NOT chat.py — chat never calls TTS). Lets logs show whether a request arrived vs hung at TTS.

**Silence safeguard:** 4.5 min idle → "Still there?" TTS check-in → 30s → pause. Activity tracked: user utterance finalized, TTS playback start.

**isPaid:** `!isGuest && subscriptionTier !== "free"` (includes basic, premium, power, elite). Conversation mode is gated on `isPaid && ttsEnabled && CONV_MODE_SUPPORTED`.

**Vite proxy for WS:** Added `ws: true` to the `/companion/api` proxy config so WebSocket upgrade requests are forwarded to uvicorn on port 8001.

## Key files
- `app/routers/stt_ws.py` — WebSocket proxy endpoint
- `src/hooks/useConversationMode.ts` — client state machine + AudioWorklet + WS
- `public/pcm-processor.js` — AudioWorklet processor (served at BASE_URL + pcm-processor.js)
- `src/components/ConversationModeButton.tsx` — toggle button with state-driven UI
