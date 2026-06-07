import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

interface ConnectionMeterProps {
  score: number;
  stageName: string;
  stageMin: number;
  stageMax: number;
  relType: string;
  scoreDelta?: number;
}

const TYPE_COLORS: Record<string, { bar: string; glow: string; text: string }> = {
  romance: {
    bar: "linear-gradient(90deg, #f43f5e, #fb7185)",
    glow: "rgba(244,63,94,0.5)",
    text: "#fb7185",
  },
  mentor: {
    bar: "linear-gradient(90deg, #7c3aed, #a78bfa)",
    glow: "rgba(124,58,237,0.5)",
    text: "#a78bfa",
  },
  friendship: {
    bar: "linear-gradient(90deg, #0d9488, #2dd4bf)",
    glow: "rgba(13,148,136,0.5)",
    text: "#2dd4bf",
  },
  professional: {
    bar: "linear-gradient(90deg, #0284c7, #38bdf8)",
    glow: "rgba(2,132,199,0.5)",
    text: "#38bdf8",
  },
};

export function ConnectionMeter({
  score,
  stageName,
  stageMin,
  stageMax,
  relType,
  scoreDelta,
}: ConnectionMeterProps) {
  const colors = TYPE_COLORS[relType] ?? TYPE_COLORS.romance;
  const range = Math.max(1, stageMax - stageMin);
  const progress = Math.min(1, Math.max(0, (score - stageMin) / range));
  const prevStageRef = useRef(stageName);
  const [pulse, setPulse] = useState(false);

  useEffect(() => {
    if (prevStageRef.current !== stageName) {
      prevStageRef.current = stageName;
      setPulse(true);
      const t = setTimeout(() => setPulse(false), 1200);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [stageName]);

  const showDelta = scoreDelta !== undefined && scoreDelta !== 0;

  return (
    <div className="px-4 pb-2 shrink-0">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1.5">
          <AnimatePresence mode="wait">
            <motion.span
              key={stageName}
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 4 }}
              className="text-xs font-semibold"
              style={{ color: colors.text }}
            >
              {stageName}
            </motion.span>
          </AnimatePresence>
        </div>
        <div className="flex items-center gap-1.5">
          {showDelta && (
            <motion.span
              key={`delta-${score}`}
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="text-[10px] font-medium"
              style={{ color: scoreDelta! > 0 ? "#4ade80" : "#f87171" }}
            >
              {scoreDelta! > 0 ? `+${scoreDelta}` : scoreDelta}
            </motion.span>
          )}
          <span className="text-[10px] text-white/30">{score}/100</span>
        </div>
      </div>

      {/* Progress bar */}
      <div
        className="relative h-1.5 rounded-full overflow-hidden"
        style={{ background: "rgba(255,255,255,0.08)" }}
      >
        <motion.div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ background: colors.bar }}
          animate={{ width: `${progress * 100}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
        {/* Pulse overlay on stage-up */}
        {pulse && (
          <motion.div
            className="absolute inset-0 rounded-full"
            style={{ background: colors.bar, boxShadow: `0 0 12px ${colors.glow}` }}
            initial={{ opacity: 0.8 }}
            animate={{ opacity: 0 }}
            transition={{ duration: 1.2, ease: "easeOut" }}
          />
        )}
      </div>
    </div>
  );
}
