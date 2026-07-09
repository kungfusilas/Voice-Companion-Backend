/**
 * useConversationMode — Always-on hands-free conversation loop.
 *
 * Manages the full voice pipeline for paid users:
 *   Mic (AudioWorklet PCM) → backend WS proxy → Deepgram live STT
 *   Deepgram events → turn detection → chat pipeline → TTS → barge-in detection
 *
 * Constraints enforced here:
 *  • Only real words (≥3) at confidence ≥0.5 trigger barge-in — not noise.
 *  • Echo cancellation via getUserMedia constraints; text-based echo guard as fallback.
 *  • Silence safeguard: 4.5 min idle → "Still there?" check-in → 30s → pause.
 *  • Voice quota billed server-side per finalized utterance only (idle listening never billed).
 */

import { useRef, useState, useCallback, useEffect, type RefObject } from "react";
import { clientLog } from "@/lib/api";

export type ConvState = "off" | "listening" | "processing" | "speaking" | "paused";

export interface ConversationModeOptions {
  enabled: boolean;               // paid tier + feature available
  sessionId: string;
  personaId: string;
  getToken: () => Promise<string | null>;
  isPlaying: boolean;             // from useAudioPlayer — drives state transitions
  isBusyRef: RefObject<boolean>;  // Chat busy ref — gate for new turns
  currentTtsTextRef: RefObject<string>; // current companion TTS text for echo detection
  onTranscriptFinalized: (text: string) => void;
  onBargeIn: (companionText: string, userWords: string) => void;
  onSilenceCheckin: () => void;   // companion says "Still there?"
  onSilencePause: () => void;     // close mic, show paused state
  onError: (msg: string) => void;
}

/** Is the browser capable of running conversation mode? */
export const CONV_MODE_SUPPORTED =
  typeof AudioWorkletNode !== "undefined" &&
  typeof AudioContext !== "undefined" &&
  typeof WebSocket !== "undefined" &&
  typeof navigator !== "undefined" &&
  !!navigator.mediaDevices?.getUserMedia;

// ── Echo detection ────────────────────────────────────────────────────────────

/**
 * Returns true if the transcript is likely a microphone echo of the companion's
 * voice coming through the speakers (i.e. the transcript is a substring of the
 * TTS text that is currently playing).
 */
function isEchoOf(transcript: string, ttsText: string): boolean {
  if (!ttsText || !transcript) return false;
  const t = transcript.toLowerCase().trim();
  if (t.length < 12) return false; // very short phrases can coincidentally match
  return ttsText.toLowerCase().includes(t);
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useConversationMode(opts: ConversationModeOptions) {
  const {
    enabled,
    sessionId,
    getToken,
    isPlaying,
    isBusyRef,
    currentTtsTextRef,
    onTranscriptFinalized,
    onBargeIn,
    onSilenceCheckin,
    onSilencePause,
    onError,
  } = opts;

  const [state, setState] = useState<ConvState>("off");
  const [interimTranscript, setInterimTranscript] = useState("");

  // Mirror state in a ref so async callbacks see the latest value
  const stateRef = useRef<ConvState>("off");

  // Accumulates finalized transcript fragments for the CURRENT utterance so the
  // whole sentence is sent, not just the last `speech_final` fragment.
  const finalTranscriptRef = useRef("");

  const _setState = useCallback((s: ConvState) => {
    stateRef.current = s;
    setState(s);
  }, []);

  // ── Resource refs ──────────────────────────────────────────────────────────
  const streamRef   = useRef<MediaStream | null>(null);
  const ctxRef      = useRef<AudioContext | null>(null);
  const workletRef  = useRef<AudioWorkletNode | null>(null);
  const wsRef       = useRef<WebSocket | null>(null);

  // ── Silence-safeguard refs ─────────────────────────────────────────────────
  const lastActivityRef    = useRef(0);
  const checkinSentRef     = useRef(false);
  const checkinTimerRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
  const silenceIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Stable ref to stopConversation (avoids circular deps) ─────────────────
  const stopRef = useRef<(target?: ConvState) => void>(() => {});

  // ── isPlaying → state transitions ─────────────────────────────────────────

  const prevPlayingRef = useRef(false);
  useEffect(() => {
    const wasPlaying = prevPlayingRef.current;
    prevPlayingRef.current = isPlaying;

    if (!enabled) return;
    const s = stateRef.current;
    if (s === "off" || s === "paused") return;

    if (isPlaying && !wasPlaying) {
      // TTS just started → companion is speaking
      _setState("speaking");
      lastActivityRef.current = Date.now();
    } else if (!isPlaying && wasPlaying) {
      // TTS just ended → ready to listen again
      if (stateRef.current === "speaking") {
        _setState("listening");
        lastActivityRef.current = Date.now();
      }
    }
  }, [isPlaying, enabled, _setState]);

  // ── Cleanup ────────────────────────────────────────────────────────────────

  const stopConversation = useCallback((target: ConvState = "off") => {
    // Timers
    if (silenceIntervalRef.current) {
      clearInterval(silenceIntervalRef.current);
      silenceIntervalRef.current = null;
    }
    if (checkinTimerRef.current) {
      clearTimeout(checkinTimerRef.current);
      checkinTimerRef.current = null;
    }
    checkinSentRef.current = false;

    // Audio pipeline
    try { workletRef.current?.disconnect(); } catch {}
    workletRef.current = null;

    streamRef.current?.getTracks().forEach(t => { try { t.stop(); } catch {} });
    streamRef.current = null;

    try { ctxRef.current?.close(); } catch {}
    ctxRef.current = null;

    // WebSocket
    try { wsRef.current?.close(); } catch {}
    wsRef.current = null;

    finalTranscriptRef.current = "";
    setInterimTranscript("");
    _setState(target);
  }, [_setState]);

  // Keep the stable ref updated
  useEffect(() => { stopRef.current = stopConversation; }, [stopConversation]);

  // ── Silence safeguard ──────────────────────────────────────────────────────

  const startSilenceTimer = useCallback(() => {
    if (silenceIntervalRef.current) clearInterval(silenceIntervalRef.current);

    silenceIntervalRef.current = setInterval(() => {
      const s = stateRef.current;
      if (s === "off" || s === "paused") return;

      const idleMs = Date.now() - lastActivityRef.current;

      if (idleMs > 270_000 && !checkinSentRef.current) {
        // 4.5 min idle → send check-in
        checkinSentRef.current = true;
        clientLog("conv_silence_checkin", { idle_ms: idleMs });
        onSilenceCheckin();

        // 30 s window for user to respond
        checkinTimerRef.current = setTimeout(() => {
          const stillIdleMs = Date.now() - lastActivityRef.current;
          if (stillIdleMs > 295_000) {
            clientLog("conv_silence_pause", { idle_ms: stillIdleMs });
            onSilencePause();
            stopRef.current("paused");
          }
        }, 30_000);
      }
    }, 10_000);
  }, [onSilenceCheckin, onSilencePause]);

  // ── Deepgram event handler ─────────────────────────────────────────────────

  const handleDgEvent = useCallback((raw: string) => {
    let evt: Record<string, unknown>;
    try { evt = JSON.parse(raw); } catch { return; }

    const type = evt.type as string;

    if (type === "connected") {
      clientLog("conv_ws_connected", { tier: evt.tier });
      return;
    }

    if (type === "error") {
      clientLog("conv_ws_error", { message: evt.message });
      onError(String(evt.message ?? "Streaming error"));
      stopRef.current("off");
      return;
    }

    if (type === "SpeechStarted") {
      clientLog("conv_speech_started", {});
      return;
    }

    if (type !== "Results") return;

    // ── Transcript result ──────────────────────────────────────────────────
    const channel = (evt.channel as Record<string, unknown>) ?? {};
    const alts    = (channel.alternatives as unknown[]) ?? [];
    const alt     = (alts[0] ?? {}) as Record<string, unknown>;
    const text     = ((alt.transcript as string) ?? "").trim();
    const conf     = (alt.confidence as number) ?? 0;
    const isFinal  = evt.is_final === true;
    const spFinal  = evt.speech_final === true;

    if (!text) return;

    const curState = stateRef.current;

    // ── Barge-in detection (while companion is speaking) ───────────────────
    if (curState === "speaking") {
      const words = text.split(/\s+/).filter(Boolean);
      if (
        words.length >= 3 &&
        conf >= 0.5 &&
        !isEchoOf(text, currentTtsTextRef.current ?? "")
      ) {
        clientLog("conv_bargein", {
          user_words: text,
          companion_text: (currentTtsTextRef.current ?? "").slice(0, 120),
          confidence: conf,
        });
        onBargeIn(currentTtsTextRef.current ?? "", text);
        lastActivityRef.current = Date.now();
        // Clear check-in countdown — user is clearly here
        if (checkinTimerRef.current) {
          clearTimeout(checkinTimerRef.current);
          checkinTimerRef.current = null;
          checkinSentRef.current = false;
        }
      }
      // Don't process as a new turn while speaking (wait for barge-in to transition state)
      return;
    }

    if (!isFinal) {
      const prefix = finalTranscriptRef.current;
      setInterimTranscript(prefix ? `${prefix} ${text}` : text);
      return;
    }

    // Accumulate finalized fragments; only the last carries speech_final, so
    // this keeps the beginning of the sentence instead of just the last words.
    if (curState === "listening") {
      finalTranscriptRef.current = finalTranscriptRef.current
        ? `${finalTranscriptRef.current} ${text}`
        : text;
      lastActivityRef.current = Date.now();

      if (!spFinal) {
        setInterimTranscript(finalTranscriptRef.current);
        return;
      }

      const fullText = finalTranscriptRef.current.trim();
      finalTranscriptRef.current = "";
      setInterimTranscript("");

      // Cancel check-in countdown — user responded
      if (checkinTimerRef.current) {
        clearTimeout(checkinTimerRef.current);
        checkinTimerRef.current = null;
        checkinSentRef.current = false;
      }

      // Don't overlap with an in-flight chat turn
      if (isBusyRef.current || !fullText) return;

      _setState("processing");
      clientLog("conv_turn", { transcript: fullText, confidence: conf });
      // Safety timeout: if TTS never starts within 25 s (e.g. network error), reopen mic
      setTimeout(() => {
        if (stateRef.current === "processing") {
          _setState("listening");
          lastActivityRef.current = Date.now();
        }
      }, 25_000);
      onTranscriptFinalized(fullText);
    }
  }, [
    currentTtsTextRef,
    isBusyRef,
    onBargeIn,
    onError,
    onTranscriptFinalized,
    _setState,
  ]);

  // ── start ──────────────────────────────────────────────────────────────────

  const start = useCallback(async () => {
    if (!enabled || !CONV_MODE_SUPPORTED) return;
    const s = stateRef.current;
    if (s !== "off" && s !== "paused") return;

    // ── getUserMedia FIRST — gesture-critical on Safari ──────────────────
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (err) {
      const name = err instanceof Error ? err.name : String(err);
      onError(
        name === "NotAllowedError"
          ? "Microphone access denied — allow mic access and try again."
          : "Could not access microphone — check your device settings.",
      );
      return;
    }
    streamRef.current = stream;

    // ── Auth token ──────────────────────────────────────────────────────────
    let token: string | null;
    try {
      token = await getToken();
    } catch {
      token = null;
    }
    if (!token) {
      stream.getTracks().forEach(t => t.stop());
      streamRef.current = null;
      onError("Please sign in to use conversation mode.");
      return;
    }

    // ── AudioContext + worklet ──────────────────────────────────────────────
    let ctx: AudioContext;
    try {
      ctx = new AudioContext();
      // Resume within the gesture window so iOS/Safari allows mic capture
      ctx.resume().catch(() => {});
      await ctx.audioWorklet.addModule(
        `${import.meta.env.BASE_URL}pcm-processor.js`,
      );
    } catch {
      stream.getTracks().forEach(t => t.stop());
      streamRef.current = null;
      onError(
        "Your browser does not support the audio worklet needed for conversation mode — please try Chrome or Safari 14.5+.",
      );
      return;
    }
    ctxRef.current = ctx;
    const sampleRate = ctx.sampleRate;

    const source  = ctx.createMediaStreamSource(stream);
    const worklet = new AudioWorkletNode(ctx, "pcm-processor");
    source.connect(worklet);
    workletRef.current = worklet;

    // ── WebSocket to backend ────────────────────────────────────────────────
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl =
      `${proto}//${location.host}${import.meta.env.BASE_URL}api/stt/stream` +
      `?token=${encodeURIComponent(token)}` +
      `&sample_rate=${sampleRate}` +
      `&session_id=${encodeURIComponent(sessionId)}`;

    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      clientLog("conv_ws_open", { sample_rate: sampleRate });
      // Wire worklet → WebSocket after connection is confirmed open
      worklet.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(e.data);
        }
      };
    };

    ws.onmessage = (e) => {
      if (typeof e.data === "string") handleDgEvent(e.data);
    };

    ws.onerror = () => {
      clientLog("conv_ws_err", {});
      onError("Streaming connection failed — check your network and try again.");
      stopRef.current("off");
    };

    ws.onclose = (e) => {
      clientLog("conv_ws_close", { code: e.code });
      if (stateRef.current !== "off" && stateRef.current !== "paused") {
        if (e.code === 4001) onError("Authentication failed — please sign in again.");
        else if (e.code === 4003) onError("Conversation mode requires a paid plan.");
        _setState("off");
      }
    };

    finalTranscriptRef.current = "";
    lastActivityRef.current = Date.now();
    _setState("listening");
    startSilenceTimer();
    clientLog("conv_started", { sample_rate: sampleRate, session_id: sessionId });
  }, [
    enabled,
    sessionId,
    getToken,
    handleDgEvent,
    _setState,
    startSilenceTimer,
    onError,
  ]);

  // ── stop (public) ──────────────────────────────────────────────────────────

  const stop = useCallback(() => {
    clientLog("conv_stopped_by_user", {});
    stopConversation("off");
  }, [stopConversation]);

  // ── Unmount cleanup ────────────────────────────────────────────────────────

  useEffect(() => {
    return () => { stopRef.current("off"); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return { state, interimTranscript, start, stop };
}
