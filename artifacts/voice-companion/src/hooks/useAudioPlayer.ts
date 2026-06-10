import { useRef, useState, useCallback } from "react";

export function useAudioPlayer() {
  const [playing, setPlaying] = useState(false);

  // AudioContext stays "unlocked" after the first user gesture, meaning
  // audio can play reliably even after a long async chain (STT → chat → TTS).
  // HTML Audio requires an active user gesture at the moment play() is called,
  // which fails when ~8-12s have elapsed since the push-to-talk button press.
  const ctxRef    = useRef<AudioContext | null>(null);
  const sourceRef = useRef<AudioBufferSourceNode | null>(null);

  const _ctx = useCallback((): AudioContext => {
    if (!ctxRef.current || ctxRef.current.state === "closed") {
      ctxRef.current = new AudioContext();
    }
    return ctxRef.current;
  }, []);

  const play = useCallback(async (blob: Blob) => {
    // Stop anything currently playing
    try { sourceRef.current?.stop(); } catch {}
    sourceRef.current = null;

    try {
      const ctx = _ctx();
      // Resume the context in case the browser suspended it
      if (ctx.state === "suspended") await ctx.resume();

      const arrayBuffer = await blob.arrayBuffer();
      const audioBuffer = await ctx.decodeAudioData(arrayBuffer);

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
      // Fallback: HTML Audio element (works when AudioContext is unavailable)
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      setPlaying(true);
      await new Promise<void>((resolve) => {
        audio.onended = () => { setPlaying(false); URL.revokeObjectURL(url); resolve(); };
        audio.onerror = () => { setPlaying(false); URL.revokeObjectURL(url); resolve(); };
        audio.play().catch(() => { setPlaying(false); URL.revokeObjectURL(url); resolve(); });
      });
    }
  }, [_ctx]);

  const stop = useCallback(() => {
    try { sourceRef.current?.stop(); } catch {}
    sourceRef.current = null;
    setPlaying(false);
  }, []);

  return { playing, play, stop };
}
