import { useRef, useState, useCallback } from "react";

export function useAudioPlayer() {
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const play = useCallback(async (blob: Blob) => {
    if (audioRef.current) {
      audioRef.current.pause();
      URL.revokeObjectURL(audioRef.current.src);
    }
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audioRef.current = audio;
    setPlaying(true);

    await new Promise<void>((resolve) => {
      audio.onended = () => {
        setPlaying(false);
        URL.revokeObjectURL(url);
        resolve();
      };
      audio.onerror = () => {
        setPlaying(false);
        resolve();
      };
      audio.play().catch(() => {
        setPlaying(false);
        resolve();
      });
    });
  }, []);

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      setPlaying(false);
    }
  }, []);

  return { playing, play, stop };
}
