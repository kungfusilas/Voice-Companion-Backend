import { useRef, useState, useCallback } from "react";
import { clientLog } from "@/lib/api";

// Computed once at load time — stable across renders
const MSE_SUPPORTED =
  typeof MediaSource !== "undefined" &&
  MediaSource.isTypeSupported("audio/mpeg");

/**
 * Minimal 46-byte WAV: 1 channel, 16-bit PCM, 44100 Hz, 1 silent sample.
 * Used to "bless" audio elements during a user gesture so that later async
 * play() calls succeed on iOS Safari without a live gesture.
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

  // PRIMARY singleton element — blessed during gesture, reused across plays.
  // Exclusive path on Safari/iOS; fallback on Chrome/Firefox.
  const singletonElRef      = useRef<HTMLAudioElement | null>(null);
  const singletonBlobUrlRef = useRef<string | null>(null);

  // PRE-BUFFER element — a second blessed element used exclusively for
  // pre-loading leg 2 audio WHILE leg 1 is still playing on the singleton.
  // Eliminates browser-side MP3 buffering from the inter-sentence gap.
  const prepElRef      = useRef<HTMLAudioElement | null>(null);
  const prepBlobUrlRef = useRef<string | null>(null);
  const prepBlobRef    = useRef<Blob | null>(null);

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

  /** Return the pre-buffer element, creating it on first call. */
  const _prepEl = useCallback((): HTMLAudioElement => {
    if (!prepElRef.current) {
      const el = new Audio();
      el.preload = "auto";
      prepElRef.current = el;
    }
    return prepElRef.current;
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

    // Clear pre-buffer state
    if (prepBlobUrlRef.current) {
      URL.revokeObjectURL(prepBlobUrlRef.current);
      prepBlobUrlRef.current = null;
    }
    prepBlobRef.current = null;
    const prepEl = prepElRef.current;
    if (prepEl) {
      prepEl.onended = null;
      prepEl.onerror = null;
      try { prepEl.pause(); prepEl.src = ""; } catch {}
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

  // ── _playPrepEl ───────────────────────────────────────────────────────────

  /**
   * Internal: play using the pre-buffer element (already has src set + load()
   * called). The browser has been buffering the MP3 while leg 1 played, so
   * this starts with near-zero latency.
   *
   * Falls back to _playSingleton if the pre-buffer element is unavailable or
   * its play() call is rejected.
   */
  const _playPrepEl = useCallback(
    async (blob: Blob, abortSignal: AbortSignal, logLabel: string): Promise<void> => {
      if (abortSignal.aborted) return;

      const el  = prepElRef.current;
      const url = prepBlobUrlRef.current;

      // Guard: if prep state is gone, fall back to singleton
      if (!el || !url) {
        clientLog("tts_prepel_miss", { label: logLabel });
        await _playSingleton(blob, abortSignal, logLabel);
        return;
      }

      // Clear prep refs now — stop() won't double-revoke
      prepBlobRef.current    = null;
      prepBlobUrlRef.current = null;

      setPlaying(true);

      await new Promise<void>((resolve) => {
        if (abortSignal.aborted) { URL.revokeObjectURL(url); resolve(); return; }

        let safetyTimer: ReturnType<typeof setTimeout>;
        let settled = false;

        const cleanup = (reason: string) => {
          if (settled) return;
          settled = true;
          clearTimeout(safetyTimer);
          el.onended = null;
          el.onerror = null;
          abortSignal.removeEventListener("abort", onAbort);
          setPlaying(false);
          URL.revokeObjectURL(url);
          try { el.src = ""; } catch {}
          clientLog("tts_el_done", { label: logLabel, reason });
          resolve();
        };

        const onAbort = () => cleanup("aborted");

        safetyTimer = setTimeout(() => cleanup("timeout"), 120_000);
        el.onended = () => cleanup("ended");
        el.onerror = () => {
          clientLog("tts_el_error", {
            label: logLabel,
            code: String(el.error?.code ?? -1),
          });
          // prepEl error → fall back to singleton
          settled = true;
          clearTimeout(safetyTimer);
          el.onended = null;
          el.onerror = null;
          abortSignal.removeEventListener("abort", onAbort);
          URL.revokeObjectURL(url);
          try { el.src = ""; } catch {}
          setPlaying(false);
          _playSingleton(blob, abortSignal, `${logLabel}_fb`).then(resolve).catch(() => resolve());
        };
        abortSignal.addEventListener("abort", onAbort, { once: true });

        el.play()
          .then(() => { clientLog("tts_el_play_ok", { label: logLabel }); })
          .catch((err: unknown) => {
            const name = err instanceof Error ? err.name : String(err);
            clientLog("tts_el_play_rejected", { label: logLabel, errorName: name });
            // play() rejected — fall back to singleton
            settled = true;
            clearTimeout(safetyTimer);
            el.onended = null;
            el.onerror = null;
            abortSignal.removeEventListener("abort", onAbort);
            URL.revokeObjectURL(url);
            try { el.src = ""; } catch {}
            setPlaying(false);
            _playSingleton(blob, abortSignal, `${logLabel}_fb`).then(resolve).catch(() => resolve());
          });
      });
    },
    [_playSingleton],
  );

  // ── prepare ───────────────────────────────────────────────────────────────

  /**
   * Pre-buffer a blob on the second blessed element so that the subsequent
   * play() call starts with near-zero latency.
   *
   * Call this as soon as the bytes land — even while another track is playing.
   * The browser will buffer the MP3 in parallel. By the time the current track
   * ends and play() is called, playback starts on the "ended" event with no
   * fetch/decode work remaining.
   *
   * Only effective on non-MSE browsers (Safari / iOS). On MSE-capable browsers
   * the stream path is used instead and buffering is already incremental.
   */
  const prepare = useCallback((blob: Blob, logLabel: string): void => {
    if (MSE_SUPPORTED) return; // Chrome/Firefox use the stream path — no-op

    // Revoke any stale pre-buffer URL
    if (prepBlobUrlRef.current) {
      URL.revokeObjectURL(prepBlobUrlRef.current);
      prepBlobUrlRef.current = null;
    }
    prepBlobRef.current = null;

    const url = URL.createObjectURL(blob);
    prepBlobUrlRef.current = url;
    prepBlobRef.current    = blob;

    const prepEl = _prepEl();
    prepEl.onended = null;
    prepEl.onerror = null;
    prepEl.src = url;
    prepEl.load(); // browser starts buffering the MP3 now, in the background

    clientLog("tts_prepare", { label: logLabel, bytes: blob.size });
  }, [_prepEl]);

  // ── play ──────────────────────────────────────────────────────────────────

  /**
   * Play a pre-downloaded audio blob.
   *
   * Non-MSE browsers (Safari / all iOS):
   *   If prepare() was called with this same blob earlier, uses the pre-buffer
   *   element (already loaded → near-zero latency). Otherwise falls back to
   *   the persistent singleton element with a fresh load().
   *
   * MSE-capable browsers (Chrome / Firefox):
   *   Tries WebAudio / AudioContext first (lower latency, gapless).
   *   Falls back to the singleton element if:
   *     • AudioContext.resume() doesn't reach "running" within 500 ms, OR
   *     • decodeAudioData throws (e.g. corrupt / incompatible audio data).
   */
  const play = useCallback(
    async (blob: Blob, logLabel = "play"): Promise<void> => {
      // Voice-unavailable / text-only response — nothing to play. Treat as a
      // clean no-op so a TTS failure never surfaces as a decode error.
      if (!blob || blob.size === 0) {
        clientLog("tts_empty_blob", { label: logLabel });
        setPlaying(false);
        return;
      }
      // ── Non-MSE (Safari / iOS) ───────────────────────────────────────────
      // Check the pre-buffer hit BEFORE calling stop(), which would revoke the
      // prepEl's blob URL and clear prepBlobRef — making the hit permanently
      // unreachable. When a hit is detected we stop everything except the prepEl.
      if (!MSE_SUPPORTED) {
        const prepHit =
          prepBlobRef.current === blob &&
          prepElRef.current !== null &&
          prepBlobUrlRef.current !== null;

        // Abort any in-flight audio and stop the singleton.
        abortRef.current?.abort();
        abortRef.current = null;
        try { sourceRef.current?.stop(); } catch {}
        sourceRef.current = null;
        const s = singletonElRef.current;
        if (s) {
          s.onended = null;
          s.onerror = null;
          try { s.pause(); } catch {}
          if (singletonBlobUrlRef.current) {
            URL.revokeObjectURL(singletonBlobUrlRef.current);
            singletonBlobUrlRef.current = null;
          }
          try { s.src = ""; } catch {}
        }
        // Only tear down the pre-buffer element when we are NOT about to play it.
        if (!prepHit) {
          if (prepBlobUrlRef.current) {
            URL.revokeObjectURL(prepBlobUrlRef.current);
            prepBlobUrlRef.current = null;
          }
          prepBlobRef.current = null;
          const pe = prepElRef.current;
          if (pe) {
            pe.onended = null;
            pe.onerror = null;
            try { pe.pause(); pe.src = ""; } catch {}
          }
        }
        setPlaying(false);

        const abort = new AbortController();
        abortRef.current = abort;

        if (prepHit) {
          clientLog("tts_prepel_hit", { label: logLabel });
          await _playPrepEl(blob, abort.signal, logLabel);
        } else {
          await _playSingleton(blob, abort.signal, logLabel);
        }
        return;
      }

      // ── MSE-capable browsers: prefer WebAudio ───────────────────────────
      stop();
      const abort = new AbortController();
      abortRef.current = abort;
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
    [_ctx, _playPrepEl, _playSingleton, stop],
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

      // All received chunks kept for blob fallback when SourceBuffer fails mid-stream
      const chunks: Uint8Array<ArrayBuffer>[] = [];

      const appendChunk = (chunk: Uint8Array<ArrayBuffer>) =>
        new Promise<void>((resolve, reject) => {
          const onUpdateEnd = () => { sb.removeEventListener("error",     onSbError);  resolve(); };
          const onSbError   = () => {
            sb.removeEventListener("updateend", onUpdateEnd);
            reject(new Error("SourceBuffer error event"));
          };
          sb.addEventListener("updateend", onUpdateEnd, { once: true });
          sb.addEventListener("error",     onSbError,   { once: true });
          try {
            sb.appendBuffer(chunk);
          } catch (err) {
            sb.removeEventListener("updateend", onUpdateEnd);
            sb.removeEventListener("error",     onSbError);
            clientLog("tts_sb_append_err", { error: String(err) });
            reject(err);
          }
        });

      let readError: unknown = null;
      try {
        while (!abort.signal.aborted) {
          const { done, value } = await reader.read();
          if (done || abort.signal.aborted) break;
          if (value?.length) {
            const chunk = new Uint8Array(value) as Uint8Array<ArrayBuffer>;
            chunks.push(chunk);
            while (sb.updating && !abort.signal.aborted) await waitUpdate();
            if (!abort.signal.aborted) await appendChunk(chunk);
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

      // SourceBuffer failure: stop MSE, fall back to blob from collected chunks
      if (readError && !abort.signal.aborted) {
        clientLog("tts_stream_sb_fallback", { chunks: chunks.length });
        stop();
        if (chunks.length > 0) {
          const fallbackBlob = new Blob(chunks, { type: "audio/mpeg" });
          await play(fallbackBlob, "stream_sb_fb");
        }
        return;
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
   * to prime both the AudioContext and both audio elements.
   *
   * iOS Safari requires audio to originate within a user gesture. Playing a
   * tiny silent WAV on each element during the gesture "blesses" them so that
   * all future async play() calls on those elements succeed.
   */
  const unlock = useCallback(() => {
    // 1. Resume AudioContext within the gesture window
    const ctx = _ctx();
    if (ctx.state === "suspended") ctx.resume().catch(() => {});

    const blessEl = (el: HTMLAudioElement) => {
      const silentUrl = URL.createObjectURL(_silentBlob());
      el.muted = true;
      el.src   = silentUrl;
      el
        .play()
        .then(() => { el.pause(); })
        .catch(() => {})
        .finally(() => {
          el.muted = false;
          try { el.src = ""; } catch {}
          URL.revokeObjectURL(silentUrl);
        });
    };

    // 2. Bless both elements — silent WAV play marks them as user-approved
    //    for all future src-swap + play() calls, even from async contexts.
    blessEl(_singleton());
    blessEl(_prepEl());
  }, [_ctx, _singleton, _prepEl]);

  return { playing, play, prepare, playStream, stop, unlock };
}
