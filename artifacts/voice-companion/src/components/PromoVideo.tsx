import { useRef, useState } from "react";
import { Play } from "lucide-react";

const VIDEO_URL =
  "https://kyeqlkqbhwaiwwnvjrtt.supabase.co/storage/v1/object/public/marketing/Legacy%20Bond%20Commerical%20(1).mp4";

export function PromoVideo() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);

  const handlePlay = () => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = false;
    video.play().then(() => {
      setPlaying(true);
    }).catch(() => {
      // fallback: at least try muted if browser blocks
      video.muted = true;
      video.play().then(() => setPlaying(true)).catch(() => {});
    });
  };

  return (
    <div className="px-4 pb-4 shrink-0">
      {/* Section label */}
      <p className="text-[11px] text-violet-400/70 font-medium tracking-wider uppercase mb-2 text-center">
        See LegacyBond in action
      </p>

      {/* Video wrapper */}
      <div
        className="relative rounded-2xl overflow-hidden mx-auto"
        style={{
          maxWidth: 720,
          background: "#0d0a1a",
          border: "1px solid rgba(124,58,237,0.25)",
          boxShadow: "0 4px 32px rgba(124,58,237,0.15)",
          aspectRatio: "16/9",
        }}
      >
        <video
          ref={videoRef}
          src={VIDEO_URL}
          preload="metadata"
          playsInline
          controls={playing}
          onEnded={() => setPlaying(false)}
          onPause={() => {
            if (videoRef.current && videoRef.current.ended) setPlaying(false);
          }}
          style={{
            width: "100%",
            height: "100%",
            display: "block",
            objectFit: "cover",
          }}
        />

        {/* Play overlay — visible only when not playing */}
        {!playing && (
          <button
            onClick={handlePlay}
            aria-label="Play promo video"
            className="absolute inset-0 flex items-center justify-center group"
            style={{ background: "rgba(0,0,0,0.35)" }}
          >
            <span
              className="flex items-center justify-center rounded-full transition-transform duration-150 group-hover:scale-110 group-active:scale-95"
              style={{
                width: 64,
                height: 64,
                background: "linear-gradient(135deg, #7c3aed, #6d28d9)",
                boxShadow: "0 4px 24px rgba(124,58,237,0.55)",
              }}
            >
              <Play className="w-7 h-7 text-white" style={{ marginLeft: 3 }} />
            </span>
          </button>
        )}
      </div>
    </div>
  );
}
