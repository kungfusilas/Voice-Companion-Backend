import { motion } from "framer-motion";

interface AvatarProps {
  name: string;
  speaking: boolean;
  listening: boolean;
  nsfw: boolean;
}

export function Avatar({ name, speaking, listening, nsfw }: AvatarProps) {
  const initials = name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  return (
    <div className="flex flex-col items-center gap-3">
      {/* Outer pulse ring when speaking */}
      <div className="relative">
        {speaking && (
          <motion.div
            className="absolute inset-0 rounded-full"
            style={{
              background: nsfw
                ? "radial-gradient(circle, rgba(239,68,68,0.3), transparent)"
                : "radial-gradient(circle, rgba(139,92,246,0.3), transparent)",
            }}
            animate={{ scale: [1, 1.5, 1], opacity: [0.6, 0, 0.6] }}
            transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
          />
        )}
        {listening && (
          <motion.div
            className="absolute inset-0 rounded-full"
            style={{
              background:
                "radial-gradient(circle, rgba(34,197,94,0.3), transparent)",
            }}
            animate={{ scale: [1, 1.3, 1], opacity: [0.8, 0.2, 0.8] }}
            transition={{ duration: 0.8, repeat: Infinity, ease: "easeInOut" }}
          />
        )}

        <motion.div
          className="relative w-28 h-28 rounded-full flex items-center justify-center text-3xl font-bold text-white shadow-2xl select-none"
          style={{
            background: nsfw
              ? "linear-gradient(135deg, #7f1d1d, #dc2626)"
              : "linear-gradient(135deg, #4c1d95, #7c3aed)",
          }}
          animate={
            speaking
              ? { scale: [1, 1.04, 1] }
              : listening
                ? { scale: [1, 1.02, 1] }
                : { scale: 1 }
          }
          transition={{ duration: speaking ? 0.5 : 0.8, repeat: speaking || listening ? Infinity : 0 }}
        >
          {initials}
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
