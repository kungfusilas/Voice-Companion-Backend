import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Trophy, Lock } from "lucide-react";
import { getMilestones, markMilestonesSeen } from "@/lib/api";
import type { MilestoneState } from "@/lib/api";

interface JourneyPanelProps {
  companionId: string;
  companionName: string;
  onClose: () => void;
}

const BOND_LEVEL_COLORS: Record<string, { bar: string; label: string; glow: string }> = {
  Warming: { bar: "from-slate-500 to-slate-400",   label: "text-slate-300",  glow: "rgba(148,163,184,0.3)" },
  Warm:    { bar: "from-amber-600 to-amber-400",    label: "text-amber-300",  glow: "rgba(251,191,36,0.3)"  },
  Close:   { bar: "from-sky-600 to-sky-400",        label: "text-sky-300",    glow: "rgba(56,189,248,0.3)"  },
  Closest: { bar: "from-violet-600 to-violet-400",  label: "text-violet-300", glow: "rgba(167,139,250,0.3)" },
};

const CATEGORY_ORDER = ["bond", "time", "memory", "goal", "ritual", "chapter"];

function ProgressBar({ value, max, colorClass }: { value: number; max: number; colorClass: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="h-1 w-full rounded-full bg-white/10 overflow-hidden">
      <div
        className={`h-full rounded-full bg-gradient-to-r ${colorClass} transition-all duration-700`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function JourneyPanel({ companionId, companionName, onClose }: JourneyPanelProps) {
  const [loading, setLoading] = useState(true);
  const [bondScore, setBondScore] = useState(50);
  const [bondLevel, setBondLevel] = useState("Warming");
  const [milestones, setMilestones] = useState<MilestoneState[]>([]);

  useEffect(() => {
    let cancelled = false;
    getMilestones(companionId).then((data) => {
      if (cancelled) return;
      setBondScore(data.connection_score);
      setBondLevel(data.bond_level);
      setMilestones(data.milestones);
      setLoading(false);
      // Mark any unseen milestones as seen now that the user is viewing them
      const unseen = data.milestones
        .filter((m) => m.unlocked && !m.seen)
        .map((m) => m.id);
      if (unseen.length) {
        markMilestonesSeen(companionId, unseen).catch(() => {});
      }
    }).catch(() => setLoading(false));
    return () => { cancelled = true; };
  }, [companionId]);

  const colors = BOND_LEVEL_COLORS[bondLevel] ?? BOND_LEVEL_COLORS.Warming;
  const scoreBarPct = Math.min(100, bondScore);

  // Group milestones by category in display order
  const grouped: MilestoneState[][] = CATEGORY_ORDER.map((cat) =>
    milestones.filter((m) => m.category === cat)
  ).filter((g) => g.length > 0);

  const unlockedCount = milestones.filter((m) => m.unlocked).length;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="absolute inset-0 z-50 flex flex-col overflow-hidden rounded-3xl"
      style={{ background: "linear-gradient(160deg, #0a0a18 0%, #0e0620 100%)" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-5 pb-3 shrink-0">
        <div className="flex items-center gap-2">
          <Trophy className="w-4 h-4 text-amber-400" />
          <span className="text-white font-semibold text-sm">Our Journey</span>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-full text-white/40 hover:text-white/70 hover:bg-white/05 transition"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto px-5 pb-6 space-y-5">
        {loading ? (
          <div className="flex justify-center pt-12">
            <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <>


            {/* Progress summary */}
            <div className="text-center">
              <span className="text-white/30 text-xs">
                {unlockedCount} of {milestones.length} milestones unlocked
              </span>
            </div>

            {/* Milestone groups */}
            {grouped.map((group) => (
              <div key={group[0].category} className="space-y-2">
                <div className="text-white/30 text-[10px] uppercase tracking-widest px-0.5">
                  {group[0].category === "ritual" ? "Check-ins" : group[0].category.charAt(0).toUpperCase() + group[0].category.slice(1)}s
                </div>
                <div className="space-y-2">
                  {group.map((m) => (
                    <MilestoneBadge key={m.id} milestone={m} />
                  ))}
                </div>
              </div>
            ))}
          </>
        )}
      </div>
    </motion.div>
  );
}

function MilestoneBadge({ milestone: m }: { milestone: MilestoneState }) {
  const showProgress = !m.unlocked && m.progress_max > 1;

  return (
    <div
      className="flex items-center gap-3 rounded-xl px-3 py-2.5 border transition"
      style={{
        background: m.unlocked ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.02)",
        borderColor: m.unlocked ? "rgba(255,255,255,0.12)" : "rgba(255,255,255,0.05)",
      }}
    >
      {/* Icon */}
      <div
        className="text-xl w-8 h-8 flex items-center justify-center rounded-lg shrink-0"
        style={{
          background: m.unlocked ? "rgba(255,255,255,0.08)" : "rgba(255,255,255,0.03)",
          filter: m.unlocked ? "none" : "grayscale(1) opacity(0.35)",
        }}
      >
        {m.unlocked ? m.icon : <Lock className="w-3.5 h-3.5 text-white/20" />}
      </div>

      {/* Text */}
      <div className="flex-1 min-w-0">
        <div
          className="text-xs font-medium truncate"
          style={{ color: m.unlocked ? "rgba(255,255,255,0.85)" : "rgba(255,255,255,0.3)" }}
        >
          {m.title}
        </div>
        {showProgress ? (
          <div className="mt-1 space-y-0.5">
            <ProgressBar value={m.progress} max={m.progress_max} colorClass="from-violet-600 to-violet-400" />
            <div className="text-[10px] text-white/25">{m.progress} / {m.progress_max}</div>
          </div>
        ) : (
          <div className="text-[10px] mt-0.5" style={{ color: "rgba(255,255,255,0.3)" }}>
            {m.description}
          </div>
        )}
      </div>

      {/* Unlocked checkmark */}
      {m.unlocked && (
        <div className="shrink-0 w-4 h-4 rounded-full bg-emerald-500/20 flex items-center justify-center">
          <svg className="w-2.5 h-2.5 text-emerald-400" fill="none" viewBox="0 0 10 10">
            <path d="M2 5l2.5 2.5L8 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      )}
    </div>
  );
}
