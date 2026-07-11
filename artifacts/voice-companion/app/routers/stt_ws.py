"""
WebSocket endpoint: browser audio → Deepgram live transcription → browser events.

Architecture:
  browser (Int16 PCM) ──WS──► this endpoint ──WS──► Deepgram
  browser            ◄─WS─── this endpoint ◄──WS── Deepgram (transcript events)

Auth: JWT passed as ?token=<jwt> query parameter (WebSocket can't send custom headers
      in all browsers). Same JWKS verification as HTTP routes.

Billing: voice quota is deducted per finalized utterance based on Deepgram's reported
         speech duration — idle listening time is never billed.
"""

import asyncio
import json
import logging
import os

import jwt as pyjwt
import websockets
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.auth_middleware import _get_public_keys
from app.usage import check_voice_quota, get_user_tier

logger = logging.getLogger(__name__)
router = APIRouter()

PAID_TIERS = {"basic", "premium", "power", "elite"}

_DG_BASE = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-2&language=en"
    "&punctuate=true&smart_format=true"
    "&interim_results=true&vad_events=true"
    "&endpointing=500&utterance_end_ms=1000"
    "&encoding=linear16&channels=1"
)

# ── Liveness / cleanup tuning ────────────────────────────────────────────────
# The browser AudioWorklet streams PCM continuously while the mic is open, so a
# live client never goes more than a couple of seconds without sending bytes.
_HEARTBEAT_INTERVAL = 10.0   # seconds between {"type":"ping"} liveness frames to the browser
_RECV_SLICE = 5.0            # polling granularity for detecting a silent client
_CLIENT_IDLE_LIMIT = 30.0    # no audio from client for this long → client is gone, tear down
_MAX_SESSION_SECONDS = 1800  # absolute per-session cap (30 min) — defense in depth


# ── Token verification (WebSocket-safe — no FastAPI Depends here) ─────────────

async def _verify_ws_token(token: str) -> str:
    """Verify a raw JWT string; return user_id or raise ValueError."""
    try:
        header = pyjwt.get_unverified_header(token)
    except Exception:
        raise ValueError("invalid token")

    kid = header.get("kid")
    alg = header.get("alg", "ES256")
    keys = await _get_public_keys()
    candidates = [k for kid2, k in keys if kid2 == kid] or [k for _, k in keys]

    for pub_key in candidates:
        try:
            payload = pyjwt.decode(
                token, pub_key, algorithms=[alg], audience="authenticated"
            )
            user_id: str | None = payload.get("sub")
            if not user_id:
                raise ValueError("no sub")
            return user_id
        except pyjwt.ExpiredSignatureError:
            raise ValueError("token expired")
        except Exception:
            continue

    raise ValueError("invalid token signature")


# ── Quota deduction (fire-and-forget, non-fatal) ──────────────────────────────

async def _deduct(user_id: str, tier: str, secs: int, session_id: str) -> None:
    try:
        await check_voice_quota(user_id, tier, secs, session_id or None)
    except Exception:
        pass


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/stream")
async def stt_stream(
    websocket: WebSocket,
    token: str = Query(..., description="Supabase JWT"),
    sample_rate: int = Query(default=48000, description="PCM sample rate"),
    session_id: str = Query(default="", description="Chat session ID"),
):
    """
    Proxy browser PCM audio to Deepgram and forward transcript events back.
    Paid tiers only. Deducts voice quota per finalized utterance.
    """
    # ── Accept first — Starlette requires accept() before any close() ──
    await websocket.accept()

    # ── Auth ──
    try:
        user_id = await _verify_ws_token(token)
    except ValueError as exc:
        await websocket.close(code=4001, reason=str(exc))
        return

    if user_id.startswith("guest_"):
        await websocket.close(code=4003, reason="paid account required")
        return

    tier, _ = await get_user_tier(user_id)
    if tier not in PAID_TIERS:
        logger.warning("WS tier rejected: uid=%s tier=%s", user_id[:8], tier)
        await websocket.close(code=4003, reason="paid account required")
        return

    await websocket.send_json({
        "type": "connected",
        "tier": tier,
        "uid": user_id[:8],
    })

    # ── Deepgram connection ──
    api_key = os.environ.get("DEEPGRAM_API_KEY", "")
    if not api_key:
        await websocket.send_json({"type": "error", "message": "STT not configured"})
        await websocket.close()
        return

    dg_url = f"{_DG_BASE}&sample_rate={sample_rate}"

    try:
        async with websockets.connect(
            dg_url,
            additional_headers={"Authorization": f"Token {api_key}"},
        ) as dg_ws:

            # ── Task 1: browser → Deepgram ──────────────────────────────────
            # A half-open client socket (mobile network switch, backgrounded tab)
            # never delivers a close frame, so receive_bytes() would block
            # forever. Poll in short slices: if no audio arrives for
            # _CLIENT_IDLE_LIMIT the client is dead — break so the whole session
            # tears down (async-with closes Deepgram, finally closes the socket)
            # instead of pinning an upstream STT session open indefinitely.
            async def client_to_dg() -> None:
                loop = asyncio.get_event_loop()
                started = loop.time()
                idle = 0.0
                try:
                    while True:
                        if loop.time() - started > _MAX_SESSION_SECONDS:
                            logger.info(
                                "STT session hit max duration — closing uid=%s",
                                user_id[:8],
                            )
                            break
                        try:
                            data = await asyncio.wait_for(
                                websocket.receive_bytes(), timeout=_RECV_SLICE
                            )
                            idle = 0.0
                            await dg_ws.send(data)
                        except asyncio.TimeoutError:
                            idle += _RECV_SLICE
                            if idle >= _CLIENT_IDLE_LIMIT:
                                logger.info(
                                    "STT client idle %.0fs — closing dead session uid=%s",
                                    idle, user_id[:8],
                                )
                                break
                            # Brief gap — keep Deepgram warm and keep waiting.
                            try:
                                await dg_ws.send(json.dumps({"type": "KeepAlive"}))
                            except Exception:
                                break
                        except WebSocketDisconnect:
                            break
                        except Exception:
                            break
                finally:
                    # Signal Deepgram end-of-stream
                    try:
                        await dg_ws.send(json.dumps({"type": "CloseStream"}))
                    except Exception:
                        pass

            # ── Task 2: Deepgram → browser, heartbeat, quota accounting ──────
            # This is the ONLY task that writes to the browser socket, so client
            # sends never interleave. When Deepgram is quiet (user silent) the
            # recv() times out and we emit a lightweight {"type":"ping"} so the
            # browser watchdog can tell a live-but-idle line from a dead one.
            async def dg_to_client() -> None:
                try:
                    while True:
                        try:
                            msg = await asyncio.wait_for(
                                dg_ws.recv(), timeout=_HEARTBEAT_INTERVAL
                            )
                        except asyncio.TimeoutError:
                            try:
                                await websocket.send_json({"type": "ping"})
                            except Exception:
                                break
                            continue
                        except Exception:
                            break  # Deepgram connection closed

                        if isinstance(msg, bytes):
                            continue

                        # Forward raw Deepgram JSON to the browser
                        try:
                            await websocket.send_text(msg)
                        except Exception:
                            break

                        # Quota deduction on finalized utterances
                        try:
                            evt = json.loads(msg)
                            if (
                                evt.get("type") == "Results"
                                and evt.get("is_final")
                                and evt.get("speech_final")
                            ):
                                alt = (
                                    (evt.get("channel") or {})
                                    .get("alternatives", [{}])[0]
                                )
                                text = ((alt.get("transcript") or "")).strip()
                                if text:
                                    words = alt.get("words") or []
                                    if len(words) >= 2:
                                        dur = max(1, round(
                                            words[-1]["end"] - words[0]["start"]
                                        ))
                                    else:
                                        dur = 1
                                    asyncio.create_task(
                                        _deduct(user_id, tier, dur, session_id)
                                    )
                        except Exception:
                            pass
                except Exception:
                    pass

            # ── Run both tasks; cancel the other when one finishes ───────────
            t1 = asyncio.create_task(client_to_dg())
            t2 = asyncio.create_task(dg_to_client())
            _done, pending = await asyncio.wait(
                [t1, t2], return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    except Exception as exc:
        logger.error("STT stream error: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": "Stream error"})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
