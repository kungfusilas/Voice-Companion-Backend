import { useRef, useState, useCallback, useEffect } from "react";

export type RecorderState = "idle" | "recording" | "processing";

/**
 * Ordered mimeType candidates for cross-browser recording.
 * Safari only supports audio/mp4 (AAC); Chrome/Firefox support WebM.
 * Falls through to undefined so the browser can pick its own default.
 */
const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
] as const;

function pickMimeType(): string | undefined {
  for (const type of MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return undefined; // let the browser use its own default
}

/**
 * Push-to-talk voice recorder.
 *
 * `start` and `stop` are **permanently stable** (empty dep arrays) —
 * they read current state via a ref instead of closing over it.
 * This prevents Framer Motion from re-registering gesture handlers
 * mid-press whenever React re-renders (which caused the flicker + "release
 * does nothing" regression).
 *
 * `onAudio` is also kept in a ref so the latest callback is always used
 * without making start/stop unstable.
 */
export function useVoiceRecorder(
  onAudio: (blob: Blob) => void,
  onError?: (message: string) => void,
) {
  const [state, setState] = useState<RecorderState>("idle");

  const stateRef         = useRef<RecorderState>("idle");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef        = useRef<Blob[]>([]);
  const onAudioRef       = useRef(onAudio);
  const onErrorRef       = useRef(onError);

  useEffect(() => { onAudioRef.current = onAudio; },  [onAudio]);
  useEffect(() => { onErrorRef.current = onError; },  [onError]);

  const _setState = useCallback((s: RecorderState) => {
    stateRef.current = s;
    setState(s);
  }, []);

  // ── start — STABLE (no state/onAudio deps) ─────────────────────────────
  const start = useCallback(async () => {
    if (stateRef.current !== "idle") return;

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      const msg =
        err instanceof Error && err.name === "NotAllowedError"
          ? "Microphone permission denied — allow mic access and try again."
          : "Could not access microphone — please check your device settings.";
      onErrorRef.current?.(msg);
      return;
    }

    // Guard: user may have released before getUserMedia resolved
    if (stateRef.current !== "idle") {
      stream.getTracks().forEach((t) => t.stop());
      return;
    }

    // Pick the best supported mimeType — undefined lets the browser decide.
    const mimeType = pickMimeType();

    let recorder: MediaRecorder;
    try {
      recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
    } catch (err) {
      stream.getTracks().forEach((t) => t.stop());
      onErrorRef.current?.(
        "Audio recording is not supported in this browser — please try Chrome or update Safari.",
      );
      return;
    }

    // Resolved type: prefer the explicit candidate, then what the browser chose.
    const resolvedType = mimeType ?? recorder.mimeType ?? "audio/webm";
    chunksRef.current = [];

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };

    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunksRef.current, { type: resolvedType });
      _setState("processing");
      onAudioRef.current(blob);
    };

    recorder.start();
    mediaRecorderRef.current = recorder;
    _setState("recording");
  }, [_setState]); // STABLE — reads stateRef, not state

  // ── stop — STABLE (no state deps) ─────────────────────────────────────
  const stop = useCallback(() => {
    if (mediaRecorderRef.current && stateRef.current === "recording") {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current = null;
    }
  }, []); // STABLE — reads stateRef, not state

  const reset = useCallback(() => _setState("idle"), [_setState]);

  return { state, start, stop, reset };
}
