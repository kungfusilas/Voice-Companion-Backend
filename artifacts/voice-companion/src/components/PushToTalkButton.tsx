import { motion } from "framer-motion";
import { Mic, MicOff, Loader2, Lock } from "lucide-react";
import type { RecorderState } from "@/hooks/useVoiceRecorder";

interface PushToTalkButtonProps {
  state: RecorderState;
  onStart: () => void;
  onStop: () => void;
  disabled?: boolean;
  nsfw: boolean;
  isPremium?: boolean;
}

export function PushToTalkButton({ state, onStart, onStop, disabled, nsfw, isPremium = true }: PushToTalkButtonProps) {
  const isRecording = state === "recording";
  const isProcessing = state === "processing";

  const activeColor = nsfw
    ? "from-red-700 to-red-500 shadow-red-700/50"
    : "from-violet-700 to-violet-500 shadow-violet-700/50";

  const idleColor = nsfw
    ? "from-red-900/60 to-red-800/60 shadow-red-900/30"
    : "from-violet-900/60 to-violet-800/60 shadow-violet-900/30";

  if (!isPremium) {
    return (
      <div className="flex flex-col items-center gap-2">
        <div
          className="relative w-16 h-16 rounded-full flex items-center justify-center cursor-not-allowed select-none"
          style={{
            background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.08)",
          }}
          title="Two-Way Voice requires Premium"
        >
          <Mic className="w-5 h-5 text-white/20" />
          <div
            className="absolute -top-1 -right-1 w-5 h-5 rounded-full flex items-center justify-center"
            style={{ background: "rgba(139,92,246,0.85)", border: "1px solid rgba(139,92,246,0.4)" }}
          >
            <Lock className="w-2.5 h-2.5 text-white" />
          </div>
        </div>
        <span className="text-[10px] font-medium text-violet-400/60">Premium</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-2">
      <motion.button
        onPointerDown={onStart}
        onPointerUp={onStop}
        onPointerLeave={onStop}
        disabled={disabled || isProcessing}
        className={`relative w-16 h-16 rounded-full bg-gradient-to-b shadow-lg flex items-center justify-center cursor-pointer select-none outline-none disabled:opacity-40 disabled:cursor-not-allowed ${isRecording ? activeColor : idleColor}`}
        whileTap={{ scale: 0.93 }}
        animate={isRecording ? { scale: [1, 1.06, 1] } : { scale: 1 }}
        transition={{ duration: 0.5, repeat: isRecording ? Infinity : 0 }}
      >
        {isProcessing ? (
          <Loader2 className="w-6 h-6 text-white animate-spin" />
        ) : isRecording ? (
          <MicOff className="w-6 h-6 text-white" />
        ) : (
          <Mic className="w-6 h-6 text-white" />
        )}

        {isRecording && (
          <motion.div
            className="absolute inset-0 rounded-full border-2 border-white/40"
            animate={{ scale: [1, 1.4], opacity: [0.6, 0] }}
            transition={{ duration: 0.8, repeat: Infinity }}
          />
        )}
      </motion.button>
      <span className="text-xs text-white/40">
        {isProcessing ? "transcribing…" : isRecording ? "release to send" : "hold to speak"}
      </span>
    </div>
  );
}
