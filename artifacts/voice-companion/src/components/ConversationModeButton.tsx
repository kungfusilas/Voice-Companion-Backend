import { motion } from "framer-motion";
import { Mic, MicOff, Loader2, Volume2, PauseCircle, Lock } from "lucide-react";
import type { ConvState } from "@/hooks/useConversationMode";

interface ConversationModeButtonProps {
  state: ConvState;
  interimTranscript: string;
  onToggle: () => void;
  disabled?: boolean;
  nsfw: boolean;
}

export function ConversationModeButton({
  state,
  interimTranscript,
  onToggle,
  disabled,
  nsfw,
}: ConversationModeButtonProps) {
  if (true) {
    return (
      <div className="flex flex-col items-center gap-2">
        <div
          className="relative w-16 h-16 rounded-full flex items-center justify-center cursor-not-allowed select-none"
          style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}
          title="Voice is coming soon"
        >
          <Mic className="w-5 h-5 text-white/20" />
          <div
            className="absolute -top-1 -right-1 w-5 h-5 rounded-full flex items-center justify-center"
            style={{ background: 'rgba(139,92,246,0.85)', border: '1px solid rgba(139,92,246,0.4)' }}
          >
            <Lock className="w-2.5 h-2.5 text-white" />
          </div>
        </div>
        <span className="text-[10px] font-medium text-violet-400/60">Coming Soon</span>
      </div>
    );
  }

  const isOff      = state === "off";
  const isPaused   = state === "paused";
  const isListening = state === "listening";
  const isSpeaking  = state === "speaking";
  const isProcessing = state === "processing";

  const accentBase = nsfw ? "violet" : "violet";
  const activeGrad = nsfw
    ? "from-red-700 to-red-500 shadow-red-700/50"
    : "from-violet-700 to-violet-500 shadow-violet-700/50";
  const idleGrad = nsfw
    ? "from-red-900/60 to-red-800/60 shadow-red-900/30"
    : "from-violet-900/60 to-violet-800/60 shadow-violet-900/30";
  const speakGrad = nsfw
    ? "from-pink-700 to-pink-500 shadow-pink-700/50"
    : "from-indigo-700 to-violet-500 shadow-indigo-700/50";

  void accentBase; // suppress unused warning

  const isActive = !isOff && !isPaused;

  const grad = isSpeaking
    ? speakGrad
    : isListening
    ? activeGrad
    : idleGrad;

  const label = isProcessing
    ? "Thinking…"
    : isSpeaking
    ? "Speaking…"
    : isListening
    ? interimTranscript
      ? `"${interimTranscript.slice(0, 28)}${interimTranscript.length > 28 ? "…" : ""}"`
      : "Listening…"
    : isPaused
    ? "Tap to resume"
    : "Start conversation";

  function Icon() {
    if (isProcessing) return <Loader2 className="w-6 h-6 text-white animate-spin" />;
    if (isSpeaking)   return <Volume2 className="w-6 h-6 text-white" />;
    if (isListening)  return <MicOff  className="w-6 h-6 text-white" />;
    if (isPaused)     return <PauseCircle className="w-6 h-6 text-white/60" />;
    return <Mic className="w-6 h-6 text-white" />;
  }

  return (
    <div className="flex flex-col items-center gap-2">
      <motion.button
        onClick={() => { if (!disabled && !isProcessing) onToggle(); }}
        disabled={disabled || isProcessing}
        className={`relative w-16 h-16 rounded-full bg-gradient-to-b shadow-lg flex items-center justify-center select-none outline-none transition-all disabled:opacity-40 disabled:cursor-not-allowed ${grad}`}
        whileTap={{ scale: 0.93 }}
        animate={isListening ? { scale: [1, 1.06, 1] } : { scale: 1 }}
        transition={{ duration: 0.7, repeat: isListening ? Infinity : 0 }}
        title={isActive ? "Tap to end conversation" : "Tap to start conversation"}
      >
        <Icon />

        {/* Ripple for listening state */}
        {isListening && (
          <motion.div
            className="absolute inset-0 rounded-full border-2 border-white/30"
            animate={{ scale: [1, 1.5], opacity: [0.5, 0] }}
            transition={{ duration: 1.0, repeat: Infinity }}
          />
        )}

        {/* Pulse for speaking state */}
        {isSpeaking && (
          <motion.div
            className="absolute inset-0 rounded-full border-2 border-indigo-300/40"
            animate={{ scale: [1, 1.35], opacity: [0.6, 0] }}
            transition={{ duration: 0.7, repeat: Infinity }}
          />
        )}
      </motion.button>

      <span className="text-[10px] text-white/50 max-w-[100px] text-center leading-tight truncate">
        {label}
      </span>
    </div>
  );
}
