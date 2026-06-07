import { useState } from "react";
import { motion } from "framer-motion";

const AVATAR_PHOTOS: Record<string, string> = {
  "companion-aria":  "/companion/avatars/aria.jpg",
  "companion-aeva":  "/companion/avatars/aeva.jpg",
  "companion-ember": "/companion/avatars/ember.jpg",
  "companion-kai":   "/companion/avatars/kai.jpg",
};

interface AvatarProps {
  name: string;
  personaId: string;
  speaking: boolean;
  listening: boolean;
  nsfw: boolean;
}

export function Avatar({ name, personaId, speaking, listening, nsfw }: AvatarProps) {
  const [photoFailed, setPhotoFailed] = useState(false);

  const photoSrc = AVATAR_PHOTOS[personaId];
  const showPhoto = !!photoSrc && !photoFailed;

  const initials = name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative">
        {/* Speaking pulse ring */}
        {speaking && (
          <motion.div
            className="absolute inset-0 rounded-full"
            style={{
              background: nsfw
                ? "radial-gradient(circle, rgba(239,68,68,0.35), transparent)"
                : "radial-gradient(circle, rgba(139,92,246,0.35), transparent)",
            }}
            animate={{ scale: [1, 1.5, 1], opacity: [0.6, 0, 0.6] }}
            transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
          />
        )}
        {/* Listening pulse ring */}
        {listening && (
          <motion.div
            className="absolute inset-0 rounded-full"
            style={{
              background: "radial-gradient(circle, rgba(34,197,94,0.35), transparent)",
            }}
            animate={{ scale: [1, 1.3, 1], opacity: [0.8, 0.2, 0.8] }}
            transition={{ duration: 0.8, repeat: Infinity, ease: "easeInOut" }}
          />
        )}

        <motion.div
          className="relative w-28 h-28 rounded-full overflow-hidden shadow-2xl select-none"
          style={
            showPhoto
              ? {
                  boxShadow: nsfw
                    ? "0 0 0 2px rgba(239,68,68,0.5)"
                    : "0 0 0 2px rgba(139,92,246,0.45), 0 8px 32px rgba(0,0,0,0.4)",
                }
              : {
                  background: nsfw
                    ? "linear-gradient(135deg, #7f1d1d, #dc2626)"
                    : "linear-gradient(135deg, #4c1d95, #7c3aed)",
                }
          }
          animate={
            speaking
              ? { scale: [1, 1.04, 1] }
              : listening
                ? { scale: [1, 1.02, 1] }
                : { scale: 1 }
          }
          transition={{
            duration: speaking ? 0.5 : 0.8,
            repeat: speaking || listening ? Infinity : 0,
          }}
        >
          {showPhoto ? (
            <img
              src={photoSrc}
              alt={name}
              onError={() => setPhotoFailed(true)}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                objectPosition: "center top",
                display: "block",
              }}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-3xl font-bold text-white">
              {initials}
            </div>
          )}
        </motion.div>
      </div>

      <div className="flex items-center gap-2">
        <span className="text-lg font-semibold text-white">{name}</span>
        {nsfw && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-red-900/60 text-red-300 border border-red-700/50">
            18+
          </span>
        )}
      </div>

      <p className="text-xs text-white/40 h-4">
        {speaking ? "speaking…" : listening ? "listening…" : ""}
      </p>
    </div>
  );
}
