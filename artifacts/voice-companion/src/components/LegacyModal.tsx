import { motion, AnimatePresence } from "framer-motion";
import { X, Lock, BookOpen, ScrollText, Brain, Users, Mail } from "lucide-react";

interface LegacyModalProps {
  open: boolean;
  onClose: () => void;
}

const FEATURES = [
  { icon: BookOpen,   label: "Your Personal Journal",    desc: "An intimate record of your inner life" },
  { icon: ScrollText, label: "Your Life Story",          desc: "A narrative memoir written in your voice" },
  { icon: Brain,      label: "Your Wisdom Archive",      desc: "Lessons and beliefs you've built over years" },
  { icon: Users,      label: "Your Family History",      desc: "The people and moments that defined you" },
  { icon: Mail,       label: "Letters",                  desc: "Deeply personal letters written from your memories" },
];

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
              boxShadow: "0 0 60px rgba(251,191,36,0.06), 0 30px 80px rgba(0,0,0,0.8), inset 0 1px 0 rgba(251,191,36,0.08)",
            }}
          >
            {/* Ambient gold glow top */}
            <div
              className="absolute inset-x-0 top-0 h-24 pointer-events-none"
              style={{ background: "linear-gradient(180deg, rgba(251,191,36,0.06) 0%, transparent 100%)" }}
            />

            <div className="relative px-6 pt-7 pb-7">
              {/* Close */}
              <button
                onClick={onClose}
                className="absolute top-5 right-5 text-white/20 hover:text-white/50 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>

              {/* Lock badge */}
              <div className="flex items-center gap-2.5 mb-5">
                <div
                  className="w-9 h-9 rounded-xl flex items-center justify-center"
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
                    Unlocks after 5 years
                  </p>
                </div>
              </div>

              {/* Description */}
              <p className="text-white/55 text-xs leading-relaxed mb-4">
                The longer you stay, the richer your story becomes. Legacy Mode unlocks after 5 years
                of continuous BondAI use.
              </p>
              <p className="text-white/40 text-xs leading-relaxed mb-5">
                When unlocked, your years of conversations, memories, and growth become:
              </p>

              {/* Feature list */}
              <div className="space-y-3 mb-6">
                {FEATURES.map(({ icon: Icon, label, desc }) => (
                  <div key={label} className="flex items-start gap-3">
                    <div
                      className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
                      style={{
                        background: "rgba(251,191,36,0.07)",
                        border: "1px solid rgba(251,191,36,0.14)",
                      }}
                    >
                      <Icon className="w-3.5 h-3.5" style={{ color: "rgba(251,191,36,0.6)" }} />
                    </div>
                    <div>
                      <p className="text-white/75 text-xs font-medium">{label}</p>
                      <p className="text-white/30 text-[11px] leading-snug mt-0.5">{desc}</p>
                    </div>
                  </div>
                ))}
              </div>

              {/* Closing quote */}
              <div
                className="rounded-2xl px-4 py-3 mb-6"
                style={{ background: "rgba(251,191,36,0.05)", border: "1px solid rgba(251,191,36,0.10)" }}
              >
                <p
                  className="text-xs leading-relaxed italic text-center"
                  style={{ color: "rgba(251,191,36,0.55)" }}
                >
                  "Legacy Mode is not a feature. It is a gift you give yourself —
                  one conversation at a time."
                </p>
              </div>

              {/* Close button */}
              <button
                onClick={onClose}
                className="w-full py-3 rounded-2xl text-sm font-medium transition-all"
                style={{
                  background: "rgba(251,191,36,0.08)",
                  border: "1px solid rgba(251,191,36,0.18)",
                  color: "rgba(251,191,36,0.7)",
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
