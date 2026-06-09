import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Calendar, UserRound, RefreshCcw, X, MessageCircle, Clock } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { FloatingHearts } from "@/components/FloatingHearts";

interface FutureMemoryItem {
  id: string;
  type: "date_based" | "gap_based" | "pattern_based";
  person: string | null;
  description: string;
  target_date: string | null;
  last_mentioned: string | null;
  days_until: number | null;
  days_since: number | null;
}

interface FutureMemoryProps {
  onStartChat?: (prompt: string) => void;
}

function typeConfig(type: FutureMemoryItem["type"]) {
  switch (type) {
    case "date_based":
      return { Icon: Calendar, badge: "Upcoming", color: "text-violet-300", bg: "rgba(139,92,246,0.12)", border: "rgba(139,92,246,0.25)" };
    case "gap_based":
      return { Icon: UserRound, badge: "Reconnect", color: "text-rose-300", bg: "rgba(244,63,94,0.10)", border: "rgba(244,63,94,0.22)" };
    case "pattern_based":
      return { Icon: RefreshCcw, badge: "Pattern", color: "text-amber-300", bg: "rgba(251,191,36,0.10)", border: "rgba(251,191,36,0.20)" };
  }
}

function timeLabel(item: FutureMemoryItem): string {
  if (item.type === "date_based" && item.days_until !== null) {
    if (item.days_until === 0) return "Today";
    if (item.days_until === 1) return "Tomorrow";
    if (item.days_until <= 7) return `In ${item.days_until} days`;
    const weeks = Math.round(item.days_until / 7);
    return weeks === 1 ? "In 1 week" : `In ${weeks} weeks`;
  }
  if (item.type === "gap_based" && item.days_since !== null) {
    if (item.days_since === 1) return "1 day ago";
    return `${item.days_since} days ago`;
  }
  return "";
}

function buildChatPrompt(item: FutureMemoryItem): string {
  if (item.type === "date_based") {
    return `I want to talk about something coming up: ${item.description}. Can you help me think through it?`;
  }
  if (item.type === "gap_based") {
    const name = item.person ? item.person : "someone important to me";
    return `I want to reconnect with ${name}. Can you help me think about how to reach out?`;
  }
  return `${item.description} — can you help me reflect on this pattern?`;
}

function MemoryCard({
  item,
  onAct,
  onDismiss,
}: {
  item: FutureMemoryItem;
  onAct: (id: string, prompt: string) => void;
  onDismiss: (id: string) => void;
}) {
  const { Icon, badge, color, bg, border } = typeConfig(item.type);
  const tLabel = timeLabel(item);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95, y: -4 }}
      transition={{ duration: 0.25 }}
      className="rounded-2xl px-4 py-4"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
    >
      <div className="flex items-start gap-3">
        {/* Type icon */}
        <div
          className="w-8 h-8 rounded-xl flex items-center justify-center shrink-0 mt-0.5"
          style={{ background: bg, border: `1px solid ${border}` }}
        >
          <Icon className={`w-4 h-4 ${color}`} />
        </div>

        <div className="flex-1 min-w-0">
          {/* Badge + time */}
          <div className="flex items-center gap-2 mb-1.5">
            <span
              className={`text-[10px] font-semibold uppercase tracking-wider ${color}`}
              style={{ opacity: 0.8 }}
            >
              {badge}
            </span>
            {tLabel && (
              <>
                <span className="text-white/15 text-[10px]">·</span>
                <span className="flex items-center gap-0.5 text-white/30 text-[10px]">
                  <Clock className="w-2.5 h-2.5" />
                  {tLabel}
                </span>
              </>
            )}
          </div>

          {/* Description */}
          <p className="text-white/80 text-[13px] leading-snug mb-3">{item.description}</p>

          {/* Actions */}
          <button
            onClick={() => onAct(item.id, buildChatPrompt(item))}
            className="flex items-center gap-1.5 text-xs font-medium transition-all"
            style={{ color: "rgba(196,181,253,0.85)" }}
          >
            <MessageCircle className="w-3.5 h-3.5" />
            Talk about this
          </button>
        </div>

        {/* Dismiss */}
        <button
          onClick={() => onDismiss(item.id)}
          className="text-white/15 hover:text-white/40 transition-colors shrink-0 mt-0.5"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </motion.div>
  );
}

export function FutureMemory({ onStartChat }: FutureMemoryProps) {
  const [memories, setMemories]     = useState<FutureMemoryItem[]>([]);
  const [loading, setLoading]       = useState(true);
  const [floatHearts, setFloatHearts] = useState(false);

  useEffect(() => {
    apiFetch("/companion/api/future-memory")
      .then((r) => r.json())
      .then((d) => { setMemories(d.memories ?? []); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleAct = async (id: string, prompt: string) => {
    // Optimistically remove card
    setMemories((prev) => prev.filter((m) => m.id !== id));
    setFloatHearts(true);

    try {
      await apiFetch(`/companion/api/future-memory/${id}/act`, { method: "POST" });
    } catch { /* non-fatal */ }

    if (onStartChat) onStartChat(prompt);
  };

  const handleDismiss = async (id: string) => {
    setMemories((prev) => prev.filter((m) => m.id !== id));
    try {
      await apiFetch(`/companion/api/future-memory/${id}/dismiss`, { method: "POST" });
    } catch { /* non-fatal */ }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <>
      {floatHearts && <FloatingHearts count={1} onComplete={() => setFloatHearts(false)} />}

      <div className="space-y-4 pt-2">
        {/* Header blurb */}
        <div className="pb-1">
          <p className="text-white/35 text-xs leading-relaxed">
            LegacyBond AI notices important dates, people, and patterns from your conversations —
            surfacing them when the moment is right.
          </p>
        </div>

        {memories.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-14 text-center">
            <div
              className="w-20 h-20 rounded-full flex items-center justify-center mb-5"
              style={{ background: "rgba(139,92,246,0.07)", border: "1px solid rgba(139,92,246,0.13)" }}
            >
              <Calendar className="w-8 h-8 text-violet-400/40" />
            </div>
            <p className="text-white/50 text-sm font-medium mb-2">No future memories yet</p>
            <p className="text-white/25 text-xs leading-relaxed max-w-[220px]">
              Mention important dates, people, or habits in your conversations and they'll
              appear here when they need your attention.
            </p>
          </div>
        ) : (
          <AnimatePresence mode="popLayout">
            {memories.map((m) => (
              <MemoryCard key={m.id} item={m} onAct={handleAct} onDismiss={handleDismiss} />
            ))}
          </AnimatePresence>
        )}

        <p className="text-white/15 text-[10px] text-center pt-2 leading-relaxed pb-2">
          Extracted automatically from your conversations · Never shared
        </p>
      </div>
    </>
  );
}
