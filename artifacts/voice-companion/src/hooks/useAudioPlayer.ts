import { useRef, useState, useCallback } from "react";
import { clientLog } from "@/lib/api";

// Computed once at load time — stable across renders
const MSE_SUPPORTED =
  typeof MediaSource !== "undefined" &&
  MediaSource.isTypeSupported("audio/mpeg");

/**
 * Minimal 46-byte WAV: 1 channel, 16-bit PCM, 44100 Hz, 1 silent sample.
 * Used to "bless" the singleton <audio> element during a user gesture so that
 * later async play() calls succeed on iOS Safari without a live gesture.
 */
function _silentBlob(): Blob {
  return new Blob(
    [
      new Uint8Array([
        0x52, 0x49, 0x46, 0x46, 0x26, 0x00, 0x00, 0x00, // RIFF <filesize-8>
        0x57, 0x41, 0x56, 0x45, 0x66, 0x6d, 0x74, 0x20, // WAVEfmt<space>
        0x10, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, // chunkLen=16, PCM, 1ch
        0x44, 0xac, 0x00, 0x00, 0x88, 0x58, 0x01, 0x00, // sampleRate=44100, byteRate=88200
        0x02, 0x00, 0x10, 0x00, // blockAlign=2, bitsPerSample=16
        0x64, 0x61, 0x74, 0x61, 0x02, 0x00, 0x00, 0x00, // "data", dataLen=2
        0x00, 0x00, // 1 zero sample
      ]),
    ],
    { type: "audio/wav" },
  );
}

export function useAudioPlayer() {
  const [playing, setPlaying] = useState(false);

  // WebAudio path (MSE-capable browsers: Chrome, Firefox)
  const ctxRef    = useRef<AudioContext | null>(null);
  const sourceRef = useRef<AudioBufferSourceNode | null>(null);

  // Persistent singleton <audio> element — created once, kept alive, unlocked
  // during the first user gesture via unlock(). Used as the PRIMARY playback
  // path on non-MSE browsers (Safari / all iOS) and as fallback everywhere else.
  const singletonElRef      = useRef<HTMLAudioElement | null>(null);
  const singletonBlobUrlRef = useRef<string | null>(null);

  // MSE streaming path (Chrome / Firefox)
  const audioElRef = useRef<HTMLAudioElement | null>(null);
  const msRef      = useRef<MediaSource | null>(null);
  const msUrlRef   = useRef<string | null>(null);

  // Cancellation token shared by all paths
  const abortRef = useRef<AbortController | null>(null);

  // ── Internal helpers ───────────────────────────────────────────────────────

  const _ctx = useCallback((): AudioContext => {
    if (!ctxRef.current || ctxRef.current.state === "closed") {
      ctxRef.current = new AudioContext();
    }
    return ctxRef.current;
  }, []);

  /** Return the singleton element, creating it on first call. */
  const _singleton = useCallback((): HTMLAudioElement => {
    if (!singletonElRef.current) {
      const el = new Audio();
      el.preload = "auto";
      singletonElRef.current = el;
    }
    return singletonElRef.current;
  }, []);

  // ── stop ──────────────────────────────────────────────────────────────────

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;

    try { sourceRef.current?.stop(); } catch {}
    sourceRef.current = null;

    // Pause the singleton but keep it alive — it is reused across plays.
    const singleton = singletonElRef.current;
    if (singleton) {
      singleton.onended = null;
      singleton.onerror = null;
      try { singleton.pause(); } catch {}
      if (singletonBlobUrlRef.current) {
        URL.revokeObjectURL(singletonBlobUrlRef.current);
        singletonBlobUrlRef.current = null;
      }
      try { singleton.src = ""; } catch {}
    }

    // MSE path cleanup
    if (audioElRef.current) {
      try { audioElRef.current.pause(); audioElRef.current.src = ""; } catch {}
      audioElRef.current = null;
    }
    if (msRef.current?.readyState === "open") {
      try { msRef.current.endOfStream(); } catch {}
    }
    msRef.current = null;
    if (msUrlRef.current) {
      URL.revokeObjectURL(msUrlRef.current);
      msUrlRef.current = null;
    }

    setPlaying(false);
  }, []);

  // ── _playSingleton ────────────────────────────────────────────────────────

  /**
   * Internal: play a blob on the persistent singleton element.
   * Primary path for Safari/iOS; fallback for MSE browsers when WebAudio fails.
   */
  const _playSingleton = useCallback(
    async (blob: Blob, abortSignal: AbortSignal, logLabel: string): Promise<void> => {
      if (abortSignal.aborted) return;

      const singleton = _singleton();

      // Revoke any previous blob URL before assigning a new one
      if (singletonBlobUrlRef.current) {
        URL.revokeObjectURL(singletonBlobUrlRef.current);
      }
      const url = URL.createObjectURL(blob);
      singletonBlobUrlRef.current = url;

      singleton.src = url;
      singleton.load(); // reset decoder for a clean start

      setPlaying(true);

      await new Promise<void>((resolve) => {
        if (abortSignal.aborted) { resolve(); return; }

        let safetyTimer: ReturnType<typeof setTimeout>;
        let settled = false;

        const cleanup = (reason: string) => {
          if (settled) return;
          settled = true;
          clearTimeout(safetyTimer);
          singleton.onended = null;
          singleton.onerror = null;
          abortSignal.removeEventListener("abort", onAbort);
          setPlaying(false);
          if (singletonBlobUrlRef.current === url) {
            URL.revokeObjectURL(url);
            singletonBlobUrlRef.current = null;
          }
          try { singleton.src = ""; } catch {}
          clientLog("tts_el_done", { label: logLabel, reason });
          resolve();
        };

        const onAbort = () => cleanup("aborted");

        // 120 s safety timeout — prevents permanent "speaking…" for very long replies
        safetyTimer = setTimeout(() => cleanup("timeout"), 120_000);
        singleton.onended = () => cleanup("ended");
        singleton.onerror = () => {
          clientLog("tts_el_error", {
            label: logLabel,
            code: String(singleton.error?.code ?? -1),
          });
          cleanup("error");
        };
        abortSignal.addEventListener("abort", onAbort, { once: true });

        singleton
          .play()
          .then(() => { clientLog("tts_el_play_ok", { label: logLabel }); })
          .catch((err: unknown) => {
            const name = err instanceof Error ? err.name : String(err);
            clientLog("tts_el_play_rejected", { label: logLabel, errorName: name });
            cleanup("play_rejected");
          });
      });
    },
    [_singleton],
  );

  // ── play ──────────────────────────────────────────────────────────────────

  /**
   * Play a pre-downloaded audio blob.
   *
   * Non-MSE browsers (Safari / all iOS):
   *   Uses the persistent singleton element exclusively — the canonical iOS
   *   Safari pattern. The element is "blessed" by unlock() during a user
   *   gesture so that later async play() calls succeed.
   *
   * MSE-capable browsers (Chrome / Firefox):
   *   Tries WebAudio / AudioContext first (lower latency, gapless).
   *   Falls back to the singleton element if:
   *     • AudioContext.resume() doesn't reach "running" within 500 ms, OR
   *     • decodeAudioData throws (e.g. corrupt / incompatible audio data).
   */
  const play = useCallback(
    async (blob: Blob, logLabel = "play"): Promise<void> => {
      stop();
      const abort = new AbortController();
      abortRef.current = abort;

      // ── Non-MSE (Safari / iOS): singleton element is the exclusive path ──
      if (!MSE_SUPPORTED) {
        await _playSingleton(blob, abort.signal, logLabel);
        return;
      }

      // ── MSE-capable browsers: prefer WebAudio ───────────────────────────
      try {
        const ctx = _ctx();
        clientLog("tts_actx", { label: logLabel, state: ctx.state });

        if (ctx.state !== "running") {
          // 500 ms timeout: if AudioContext doesn't resume (e.g. no live
          // gesture on some browsers), fall back to the singleton element.
          const ctxRunning = await Promise.race([
            ctx.resume().then(() => ctx.state === "running"),
            new Promise<boolean>((r) => setTimeout(() => r(false), 500)),
          ]);
          clientLog("tts_actx_resume", {
            label: logLabel,
            running: ctxRunning,
            stateAfter: ctx.state,
          });
          if (!ctxRunning) {
            if (!abort.signal.aborted) {
              await _playSingleton(blob, abort.signal, `${logLabel}_ctxfb`);
            }
            return;
          }
        }
        if (abort.signal.aborted) return;

        const arrayBuffer = await blob.arrayBuffer();
        if (abort.signal.aborted) return;

        let audioBuffer: AudioBuffer;
        try {
          audioBuffer = await ctx.decodeAudioData(arrayBuffer);
          clientLog("tts_decode_ok", { label: logLabel, bytes: blob.size });
        } catch (decErr) {
          const msg = decErr instanceof Error ? decErr.message : String(decErr);
          clientLog("tts_decode_fail", { label: logLabel, bytes: blob.size, error: msg });
          if (!abort.signal.aborted) {
            await _playSingleton(blob, abort.signal, `${logLabel}_decfb`);
          }
          return;
        }
        if (abort.signal.aborted) return;

        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(ctx.destination);
        sourceRef.current = source;
        setPlaying(true);

        clientLog("tts_source_start", { label: logLabel });
        await new Promise<void>((resolve) => {
          source.onended = () => {
            clientLog("tts_source_ended", { label: logLabel });
            setPlaying(false);
            resolve();
          };
          source.start(0);
        });
      } catch (err) {
        if (abort.signal.aborted) return;
        const msg = err instanceof Error ? err.message : String(err);
        clientLog("tts_actx_err", { label: logLabel, error: msg });
        await _playSingleton(blob, abort.signal, `${logLabel}_fb`);
      }
    },
    [_ctx, _playSingleton, stop],
  );

  // ── playStream ────────────────────────────────────────────────────────────

  /**
   * Play a streaming audio Response via MediaSource Extensions.
   * Chrome / Firefox: audio starts as first chunks arrive.
   * Non-MSE browsers: should not reach this — Chat.tsx routes Safari to the
   * /tts/speak blob endpoint before this is called.
   */
  const playStream = useCallback(
    async (response: Response): Promise<void> => {
      stop();
      const abort = new AbortController();
      abortRef.current = abort;

      if (!MSE_SUPPORTED || !response.body) {
        const blob = await response.blob();
        if (abort.signal.aborted) return;
        await play(blob, "stream_fb");
        return;
      }

      // ── MSE streaming path ──────────────────────────────────────────────
      const ms  = new MediaSource();
      const url = URL.createObjectURL(ms);
      msRef.current    = ms;
      msUrlRef.current = url;

      const audio = new Audio(url);
      audioElRef.current = audio;

      const sbReady = new Promise<SourceBuffer | null>((resolve) => {
        ms.addEventListener(
          "sourceopen",
          () => {
            try { resolve(ms.addSourceBuffer("audio/mpeg")); }
            catch { resolve(null); }
          },
          { once: true },
        );
      });

      // Detect autoplay block BEFORE reading the response body.
      // sbReady waits for a browser event, giving the play() rejection microtask
      // time to propagate before we check the flag.
      let playRejected = false;
      audio.play().catch(() => { playRejected = true; });
      setPlaying(true);

      const sb = await sbReady;
      if (!sb || abort.signal.aborted) { stop(); return; }

      if (playRejected) {
        stop();
        const blob = await response.blob();
        if (!abort.signal.aborted) await play(blob, "mse_play_fb");
        return;
      }

      const reader = response.body.getReader();

      const waitUpdate = () =>
        new Promise<void>((r) =>
          sb.addEventListener("updateend", () => r(), { once: true }),
        );

      const appendChunk = (chunk: Uint8Array<ArrayBuffer>) =>
        new Promise<void>((resolve) => {
          const onUpdateEnd = () => { sb.removeEventListener("error",     onSbError);  resolve(); };
          const onSbError   = () => { sb.removeEventListener("updateend", onUpdateEnd); resolve(); };
          sb.addEventListener("updateend", onUpdateEnd, { once: true });
          sb.addEventListener("error",     onSbError,   { once: true });
          try {
            sb.appendBuffer(chunk);
          } catch {
            sb.removeEventListener("updateend", onUpdateEnd);
            sb.removeEventListener("error",     onSbError);
            resolve();
          }
        });

      let readError: unknown = null;
      try {
        while (!abort.signal.aborted) {
          const { done, value } = await reader.read();
          if (done || abort.signal.aborted) break;
          if (value?.length) {
            while (sb.updating && !abort.signal.aborted) await waitUpdate();
            if (!abort.signal.aborted) await appendChunk(new Uint8Array(value));
          }
        }
      } catch (err) {
        readError = err;
      } finally {
        reader.cancel().catch(() => {});
        if (!abort.signal.aborted && ms.readyState === "open") {
          try { ms.endOfStream(); } catch {}
        }
      }

      if (readError) {
        setPlaying(false);
        URL.revokeObjectURL(url);
        msUrlRef.current   = null;
        audioElRef.current = null;
        throw readError;
      }

      if (abort.signal.aborted) return;

      await new Promise<void>((resolve) => {
        const done = () => {
          if (abort.signal.aborted) { resolve(); return; }
          setPlaying(false);
          URL.revokeObjectURL(url);
          msUrlRef.current   = null;
          audioElRef.current = null;
          resolve();
        };
        audio.addEventListener("ended", done, { once: true });
        audio.addEventListener("error", done, { once: true });
        if (audio.ended) done();
      });
    },
    [play, stop],
  );

  // ── unlock ────────────────────────────────────────────────────────────────

  /**
   * Call synchronously inside a user-gesture handler (onClick / onPointerDown)
   * to prime both the AudioContext and the singleton element.
   *
   * iOS Safari requires audio to originate within a user gesture. Playing a
   * tiny silent WAV on the singleton element during the gesture "blesses" it
   * so that future async play() calls succeed even without another gesture.
   */
  const unlock = useCallback(() => {
    // 1. Resume AudioContext within the gesture window
    const ctx = _ctx();
    if (ctx.state === "suspended") ctx.resume().catch(() => {});

    // 2. Bless the singleton: play a tiny silent WAV, then immediately pause.
    //    This marks the element as user-approved for all future src-swap + play() calls.
    const singleton = _singleton();
    const silentUrl = URL.createObjectURL(_silentBlob());
    singleton.muted = true;
    singleton.src   = silentUrl;
    singleton
      .play()
      .then(() => { singleton.pause(); })
      .catch(() => {})
      .finally(() => {
        singleton.muted = false;
        try { singleton.src = ""; } catch {}
        URL.revokeObjectURL(silentUrl);
      });
  }, [_ctx, _singleton]);

  return { playing, play, playStream, stop, unlock };
}
