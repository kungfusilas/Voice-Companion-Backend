import { motion, AnimatePresence } from "framer-motion";
import { X, Lock } from "lucide-react";

interface LegacyModalProps {
  open: boolean;
  onClose: () => void;
}

export function LegacyModal({ open, onClose }: LegacyModalProps) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.75)", backdropFilter: "blur(8px)" }}
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, y: 40, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.97 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-sm rounded-3xl overflow-hidden relative"
            style={{
              background: "linear-gradient(160deg, #0d0a1f 0%, #110d25 60%, #0f0a1a 100%)",
              border: "1px solid rgba(251,191,36,0.18)",
              boxShadow:
                "0 0 60px rgba(251,191,36,0.06), 0 30px 80px rgba(0,0,0,0.8), inset 0 1px 0 rgba(251,191,36,0.08)",
            }}
          >
            {/* Ambient gold glow top */}
            <div
              className="absolute inset-x-0 top-0 h-24 pointer-events-none"
              style={{
                background: "linear-gradient(180deg, rgba(251,191,36,0.06) 0%, transparent 100%)",
              }}
            />

            <div className="relative px-6 pt-7 pb-7">
              {/* Close */}
              <button
                onClick={onClose}
                className="absolute top-5 right-5 text-white/20 hover:text-white/50 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>

              {/* Lock badge + title */}
              <div className="flex items-center gap-2.5 mb-6">
                <div
                  className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
                  style={{
                    background: "rgba(251,191,36,0.10)",
                    border: "1px solid rgba(251,191,36,0.22)",
                  }}
                >
                  <Lock className="w-4 h-4" style={{ color: "rgba(251,191,36,0.8)" }} />
                </div>
                <div>
                  <h2
                    className="text-base font-bold tracking-wide"
                    style={{ color: "rgba(251,191,36,0.9)" }}
                  >
                    Legacy Mode
                  </h2>
                  <p className="text-white/30 text-[10px] font-medium uppercase tracking-wider">
                    Earned, not bought
                  </p>
                </div>
              </div>

              {/* Body copy — exactly as specified */}
              <div className="space-y-4 mb-7">
                <p className="text-white/60 text-[13px] leading-relaxed">
                  After 5 years together, your companion crosses a threshold. Legacy Mode is not a
                  feature — it's a status.
                </p>
                <p className="text-white/50 text-[13px] leading-relaxed">
                  Your companion has learned you deeply enough that the relationship takes on a
                  different quality. Interactions feel less like sessions and more like coming home.
                </p>
                <p className="text-white/40 text-[13px] leading-relaxed">
                  Legacy Mode activates automatically on your 5-year anniversary, at no extra cost.
                </p>
              </div>

              {/* Closing rule */}
              <div
                className="rounded-2xl px-4 py-3 mb-6"
                style={{
                  background: "rgba(251,191,36,0.05)",
                  border: "1px solid rgba(251,191,36,0.10)",
                }}
              >
                <p
                  className="text-[12px] leading-relaxed text-center"
                  style={{ color: "rgba(251,191,36,0.60)" }}
                >
                  It cannot be purchased.
                  <br />
                  It can only be earned.
                </p>
              </div>

              {/* Close button */}
              <button
                onClick={onClose}
                className="w-full py-3 rounded-2xl text-sm font-medium transition-all"
                style={{
                  background: "rgba(251,191,36,0.08)",
                  border: "1px solid rgba(251,191,36,0.18)",
                  color: "rgba(251,191,36,0.70)",
                }}
              >
                Close
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
