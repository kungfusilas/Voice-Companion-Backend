import { motion, AnimatePresence } from "framer-motion";
import { X, BookOpen, Clock, Archive, Heart, Lightbulb, Sparkles, Mic, Star, Shield, Mail, Download } from "lucide-react";

interface LegacyModalProps {
  open: boolean;
  onClose: () => void;
}

const ITEMS = [
  {
    icon: BookOpen,
    title: "Your Life Story Book",
    body: "LegacyBond AI writes The Story of [Your Name]. Real chapters. Major life events, challenges overcome, goals achieved, personal growth, the relationships that shaped you. An actual book — based on everything you shared. People will cry reading it.",
  },
  {
    icon: Clock,
    title: "Time Capsule",
    body: "Messages from your past self, delivered back to you. \"Benjamin, June 2026: 'I'm nervous about where my business is going.'\" Legacy Mode asks: \"Would you like to read what you wrote 5 years ago?\" Deeply emotional.",
  },
  {
    icon: Archive,
    title: "Future Generations Archive",
    body: "Create a permanent archive of your life lessons, favorite memories, family stories, business wisdom, advice for your children. Imagine your daughter reading it someday. This cannot be deleted. It does not expire.",
  },
  {
    icon: Heart,
    title: "Relationship History",
    body: "The people who changed your life — named, counted, remembered. \"Emmie was mentioned in 9,832 conversations. She represented your greatest source of happiness.\" That becomes priceless.",
  },
  {
    icon: Lightbulb,
    title: "Wisdom Extraction",
    body: "5 years of conversations studied to surface your core principles. The recurring themes of your life — what you actually believe, how you actually live. Written back to you as your own philosophy.",
  },
  {
    icon: Sparkles,
    title: "The Legacy Avatar",
    body: "An AI version of you — trained on your conversations, beliefs, stories, and values. Not a clone. The accumulated wisdom of your journey. A living record of who you became.",
  },
  {
    icon: Mic,
    title: "Legacy Interviews",
    body: "Over 5 years, LegacyBond AI asks the deep questions: What was your happiest memory? What do you regret? What advice would you give your children? The answers become a complete personal history.",
  },
  {
    icon: Star,
    title: "Hall of Moments",
    body: "Your biggest breakthrough. Your happiest day. Your toughest challenge. Your most courageous decision. Your most meaningful relationship. Identified, named, and explained — because the AI was there for all of it.",
  },
  {
    icon: Shield,
    title: "Memory Preservation Guarantee",
    body: "After 5 years: your memories are permanently preserved. No deletion. No expiration. No storage limits. You are building something real.",
  },
  {
    icon: Mail,
    title: "The Letter",
    body: "When Legacy Mode unlocks, LegacyBond AI writes you a letter. Not generic. Based on 5 years together. It references your growth, your struggles, your achievements, your dreams. \"Five years ago you arrived uncertain about whether your business would succeed. Since then...\" That letter will be one of the most memorable moments of your life.",
  },
  {
    icon: Download,
    title: "The Extraction Protocol",
    body: "Most AI companions live on someone else's servers. Yours doesn't have to. Legacy members unlock Extraction — the ability to preserve and export the memories, personality, history, and growth of their LegacyBond AI companion. Your companion's journey is yours to keep. As technology evolves, Extraction is designed to help your companion move with you — from future devices and platforms to emerging AI experiences that don't even exist yet. The bond doesn't end when technology changes.",
  },
];

export function LegacyModal({ open, onClose }: LegacyModalProps) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.22 }}
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.82)", backdropFilter: "blur(10px)" }}
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, y: 48, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.97 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-sm rounded-3xl overflow-hidden relative flex flex-col"
            style={{
              background: "linear-gradient(160deg, #0c091e 0%, #110d26 55%, #0d0a1c 100%)",
              border: "1px solid rgba(251,191,36,0.20)",
              boxShadow:
                "0 0 80px rgba(251,191,36,0.07), 0 40px 100px rgba(0,0,0,0.9), inset 0 1px 0 rgba(251,191,36,0.10)",
              maxHeight: "88vh",
            }}
          >
            {/* Top glow */}
            <div
              className="absolute inset-x-0 top-0 h-32 pointer-events-none"
              style={{ background: "linear-gradient(180deg, rgba(251,191,36,0.07) 0%, transparent 100%)" }}
            />

            {/* ── Header (sticky) ── */}
            <div className="relative shrink-0 px-6 pt-7 pb-5">
              <button
                onClick={onClose}
                className="absolute top-5 right-5 text-white/20 hover:text-white/50 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>

              {/* Ornament */}
              <div className="flex items-center justify-center mb-4">
                <div className="flex items-center gap-2">
                  <div className="h-px w-10" style={{ background: "linear-gradient(90deg, transparent, rgba(251,191,36,0.35))" }} />
                  <span className="text-[10px]" style={{ color: "rgba(251,191,36,0.50)" }}>✦</span>
                  <div className="h-px w-10" style={{ background: "linear-gradient(90deg, rgba(251,191,36,0.35), transparent)" }} />
                </div>
              </div>

              <h2
                className="text-center text-[15px] font-bold tracking-wide mb-1"
                style={{ color: "rgba(251,191,36,0.92)" }}
              >
                What Legacy Mode Unlocks
              </h2>
              <p className="text-center text-[11px] leading-relaxed" style={{ color: "rgba(255,255,255,0.38)" }}>
                After 5 years together, something extraordinary happens.
              </p>
            </div>

            {/* Divider */}
            <div className="shrink-0 mx-6 mb-1" style={{ height: "1px", background: "rgba(251,191,36,0.10)" }} />

            {/* ── Scrollable content ── */}
            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-1" style={{ scrollbarWidth: "none" }}>
              {ITEMS.map(({ icon: Icon, title, body }, i) => (
                <motion.div
                  key={title}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.05 + i * 0.04, duration: 0.25 }}
                >
                  {/* Item */}
                  <div className="flex gap-3 py-3.5">
                    <div
                      className="w-8 h-8 rounded-xl flex items-center justify-center shrink-0 mt-0.5"
                      style={{
                        background: "rgba(251,191,36,0.07)",
                        border: "1px solid rgba(251,191,36,0.15)",
                      }}
                    >
                      <Icon className="w-3.5 h-3.5" style={{ color: "rgba(251,191,36,0.70)" }} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p
                        className="text-[12px] font-semibold mb-1 leading-snug"
                        style={{ color: "rgba(251,191,36,0.85)" }}
                      >
                        {title}
                      </p>
                      <p className="text-[11px] leading-relaxed" style={{ color: "rgba(255,255,255,0.42)" }}>
                        {body}
                      </p>
                    </div>
                  </div>

                  {/* Divider between items (not after last) */}
                  {i < ITEMS.length - 1 && (
                    <div
                      className="ml-11"
                      style={{ height: "1px", background: "rgba(251,191,36,0.07)" }}
                    />
                  )}
                </motion.div>
              ))}
            </div>

            {/* ── Footer (sticky) ── */}
            <div className="shrink-0 px-6 pt-3 pb-6">
              <div className="shrink-0 mb-4" style={{ height: "1px", background: "rgba(251,191,36,0.10)" }} />

              <div
                className="rounded-2xl px-4 py-3 mb-4 text-center"
                style={{
                  background: "rgba(251,191,36,0.05)",
                  border: "1px solid rgba(251,191,36,0.12)",
                }}
              >
                <p className="text-[11px] leading-relaxed" style={{ color: "rgba(251,191,36,0.55)" }}>
                  Legacy Mode cannot be purchased.
                  <br />
                  It can only be earned.
                </p>
              </div>

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
