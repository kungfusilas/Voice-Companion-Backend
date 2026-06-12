import { useRef, useState, useCallback } from "react";

// Computed once at load time — stable across renders
const MSE_SUPPORTED =
  typeof MediaSource !== "undefined" &&
  MediaSource.isTypeSupported("audio/mpeg");

export function useAudioPlayer() {
  const [playing, setPlaying] = useState(false);

  // AudioContext path (full-blob playback)
  const ctxRef    = useRef<AudioContext | null>(null);
  const sourceRef = useRef<AudioBufferSourceNode | null>(null);

  // MSE streaming path
  const audioElRef  = useRef<HTMLAudioElement | null>(null);
  const msRef       = useRef<MediaSource | null>(null);
  const msUrlRef    = useRef<string | null>(null);

  // Cancellation token shared by both paths
  const abortRef = useRef<AbortController | null>(null);

  const _ctx = useCallback((): AudioContext => {
    if (!ctxRef.current || ctxRef.current.state === "closed") {
      ctxRef.current = new AudioContext();
    }
    return ctxRef.current;
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;

    try { sourceRef.current?.stop(); } catch {}
    sourceRef.current = null;

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

  /** Play a pre-downloaded audio blob via AudioContext (HTML Audio fallback). */
  const play = useCallback(async (blob: Blob): Promise<void> => {
    stop();
    const abort = new AbortController();
    abortRef.current = abort;

    try {
      const ctx = _ctx();
      if (ctx.state === "suspended") await ctx.resume();
      if (abort.signal.aborted) return;

      const arrayBuffer = await blob.arrayBuffer();
      if (abort.signal.aborted) return;

      const audioBuffer = await ctx.decodeAudioData(arrayBuffer);
      if (abort.signal.aborted) return;

      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);
      sourceRef.current = source;
      setPlaying(true);

      await new Promise<void>((resolve) => {
        source.onended = () => { setPlaying(false); resolve(); };
        source.start(0);
      });
    } catch {
      if (abort.signal.aborted) return;
      // Fallback: HTML Audio element (when AudioContext is unavailable)
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioElRef.current = audio;
      setPlaying(true);
      await new Promise<void>((resolve) => {
        const cleanup = () => {
          setPlaying(false);
          URL.revokeObjectURL(url);
          audioElRef.current = null;
          resolve();
        };
        audio.onended = cleanup;
        audio.onerror = cleanup;
        audio.play().catch(cleanup);
      });
    }
  }, [_ctx, stop]);

  /**
   * Play a streaming audio Response.
   * Chrome/Firefox: MediaSource Extensions — audio starts as first chunks arrive.
   * Safari/iOS: collects full blob then plays (MSE unsupported there).
   */
  const playStream = useCallback(async (response: Response): Promise<void> => {
    stop();
    const abort = new AbortController();
    abortRef.current = abort;

    if (!MSE_SUPPORTED || !response.body) {
      // Fallback: collect full blob, then hand to play()
      const blob = await response.blob();
      if (abort.signal.aborted) return;
      await play(blob);
      return;
    }

    // ── MSE streaming path ──────────────────────────────────────────
    const ms  = new MediaSource();
    const url = URL.createObjectURL(ms);
    msRef.current    = ms;
    msUrlRef.current = url;

    const audio = new Audio(url);
    audioElRef.current = audio;

    // SourceBuffer is only available after sourceopen fires
    const sbReady = new Promise<SourceBuffer | null>((resolve) => {
      ms.addEventListener("sourceopen", () => {
        try { resolve(ms.addSourceBuffer("audio/mpeg")); }
        catch  { resolve(null); }
      }, { once: true });
    });

    // Start the audio element immediately — it buffers while chunks arrive
    audio.play().catch(() => {});
    setPlaying(true);

    const sb = await sbReady;
    if (!sb || abort.signal.aborted) { stop(); return; }

    const reader = response.body.getReader();

    const waitUpdate = () =>
      new Promise<void>((r) => sb.addEventListener("updateend", () => r(), { once: true }));

    const appendChunk = (chunk: Uint8Array<ArrayBuffer>) =>
      new Promise<void>((resolve) => {
        // Always resolve — a bad chunk is skipped, not fatal to the whole stream.
        const onUpdateEnd = () => { sb.removeEventListener("error",     onSbError);  resolve(); };
        const onSbError   = () => { sb.removeEventListener("updateend", onUpdateEnd); resolve(); };
        sb.addEventListener("updateend", onUpdateEnd, { once: true });
        sb.addEventListener("error",     onSbError,   { once: true });
        try {
          sb.appendBuffer(chunk);
        } catch {
          sb.removeEventListener("updateend", onUpdateEnd);
          sb.removeEventListener("error",     onSbError);
          resolve(); // QuotaExceededError etc — skip chunk, keep going
        }
      });

    // Capture any body-read error so we can reset state before re-throwing.
    let readError: unknown = null;
    try {
      while (!abort.signal.aborted) {
        const { done, value } = await reader.read();
        if (done || abort.signal.aborted) break;
        if (value?.length) {
          // Wait for any in-flight appendBuffer to complete before appending next chunk
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

    // If the body read failed, reset the speaking indicator immediately and
    // re-throw so the caller's catch block can handle the error (e.g. show retry).
    if (readError) {
      setPlaying(false);
      URL.revokeObjectURL(url);
      msUrlRef.current   = null;
      audioElRef.current = null;
      throw readError;
    }

    if (abort.signal.aborted) return; // stop() already cleaned up

    // Wait for the audio element to finish playing naturally
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
  }, [play, stop]);

  /**
   * Call this synchronously inside a user-gesture handler (e.g. onPointerDown)
   * to prime the AudioContext for iOS Safari, which requires resume() to be
   * called within a gesture before any async audio playback can succeed.
   */
  const unlock = useCallback(() => {
    const ctx = _ctx();
    if (ctx.state === "suspended") {
      ctx.resume().catch(() => {});
    }
  }, [_ctx]);

  return { playing, play, playStream, stop, unlock };
}
