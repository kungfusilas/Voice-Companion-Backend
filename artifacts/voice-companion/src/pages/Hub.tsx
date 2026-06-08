import { useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, Sparkles, BookOpen, Target, Activity, CalendarHeart, Lock, Drama, BarChart2, Brain } from "lucide-react";
import { MemoryThreads } from "./MemoryThreads";
import { BondJournal } from "./BondJournal";
import { ConnectionGoals } from "./ConnectionGoals";
import { BondScore } from "./BondScore";
import { FutureMemory } from "./FutureMemory";
import { RoleplaySimulator } from "./RoleplaySimulator";
import { WeeklyInsight } from "./WeeklyInsight";
import { PersonalityMap } from "./PersonalityMap";
import { LegacyModal } from "@/components/LegacyModal";
import type { Persona } from "@/lib/api";

interface HubProps {
  onBack: () => void;
  userId: string;
  currentPersona: Persona | null;
  onStartChat?: (prompt: string) => void;
  subscriptionTier?: string;
  subscribedAt?: string | null;
}

const BASE_TABS = [
  { id: "bond-score",      label: "Bond Score",          icon: Activity      },
  { id: "future-memory",   label: "Future Memory",       icon: CalendarHeart },
  { id: "memory",          label: "Memory Threads",      icon: Sparkles      },
  { id: "journal",         label: "Bond Journal",        icon: BookOpen      },
  { id: "goals",           label: "Connection Goals",    icon: Target        },
  { id: "roleplay",        label: "Roleplay Simulator",  icon: Drama         },
] as const;

const PREMIUM_TABS = [
  { id: "weekly-insight",  label: "Weekly Insight",      icon: BarChart2     },
] as const;

const POWER_TABS = [
  { id: "your-profile",    label: "Your Profile",        icon: Brain         },
] as const;

type BaseTab    = typeof BASE_TABS[number]["id"];
type PremiumTab = typeof PREMIUM_TABS[number]["id"];
type PowerTab   = typeof POWER_TABS[number]["id"];
type Tab = BaseTab | PremiumTab | PowerTab;

const BG: React.CSSProperties = {
  background: "linear-gradient(145deg, #0d0d1a 0%, #0f0720 50%, #0d0d1a 100%)",
};

const LEGACY_TARGET_MONTHS = 60; // 5 years

function useLegacyProgress(subscribedAt: string | null | undefined) {
  return useMemo(() => {
    if (!subscribedAt) return null;

    const start = new Date(subscribedAt);
    if (isNaN(start.getTime())) return null;

    const now = new Date();
    const totalMs = now.getTime() - start.getTime();
    const msPerMonth = 1000 * 60 * 60 * 24 * 30.4375;
    const monthsMember = Math.floor(totalMs / msPerMonth);
    const progress = Math.min(monthsMember / LEGACY_TARGET_MONTHS, 1);

    const remainingMonths = Math.max(LEGACY_TARGET_MONTHS - monthsMember, 0);
    const yearsLeft  = Math.floor(remainingMonths / 12);
    const monthsLeft = remainingMonths % 12;

    let timeUntil = "";
    if (remainingMonths <= 0) {
      timeUntil = "unlocked";
    } else if (yearsLeft > 0 && monthsLeft > 0) {
      timeUntil = `${yearsLeft}y ${monthsLeft}mo`;
    } else if (yearsLeft > 0) {
      timeUntil = `${yearsLeft} year${yearsLeft !== 1 ? "s" : ""}`;
    } else {
      timeUntil = `${monthsLeft} month${monthsLeft !== 1 ? "s" : ""}`;
    }

    let memberFor = "";
    if (monthsMember < 1) {
      memberFor = "less than a month";
    } else if (monthsMember < 12) {
      memberFor = `${monthsMember} month${monthsMember !== 1 ? "s" : ""}`;
    } else {
      const y = Math.floor(monthsMember / 12);
      const m = monthsMember % 12;
      memberFor = m > 0 ? `${y}y ${m}mo` : `${y} year${y !== 1 ? "s" : ""}`;
    }

    return { progress, timeUntil, memberFor, unlocked: remainingMonths <= 0 };
  }, [subscribedAt]);
}

export function Hub({ onBack, userId, currentPersona, onStartChat, subscriptionTier = "free", subscribedAt }: HubProps) {
  const isPremiumHub = ["premium", "power", "elite"].includes(subscriptionTier);
  const isPowerHub   = ["power", "elite"].includes(subscriptionTier);
  const [tab, setTab] = useState<Tab>("bond-score");
  const [legacyOpen, setLegacyOpen] = useState(false);
  const legacy = useLegacyProgress(subscribedAt);

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      className="flex flex-col min-h-screen"
      style={BG}
    >
      {/* Header */}
      <div className="shrink-0 px-5 pt-6 pb-3">
        <div className="flex items-center gap-3 mb-5">
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 text-white/40 hover:text-white/70 transition-colors text-sm"
          >
            <ArrowLeft className="w-4 h-4" />
            Back
          </button>
        </div>

        <h1 className="text-xl font-bold text-white mb-1">BondAI Features</h1>
        <p className="text-white/35 text-xs">Your relationship intelligence hub</p>

        {/* Tab bar */}
        <div className="flex gap-1 mt-5 overflow-x-auto pb-1 scrollbar-none">
          {BASE_TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium whitespace-nowrap transition-all shrink-0 ${
                tab === id
                  ? "bg-violet-600/40 text-white border border-violet-500/40"
                  : "text-white/40 hover:text-white/60 border border-transparent"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}

          {/* Premium-only tabs */}
          {isPremiumHub && PREMIUM_TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium whitespace-nowrap transition-all shrink-0 ${
                tab === id
                  ? "bg-violet-600/40 text-white border border-violet-500/40"
                  : "text-white/40 hover:text-white/60 border border-transparent"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}

          {/* Power-only tabs */}
          {isPowerHub && POWER_TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium whitespace-nowrap transition-all shrink-0 ${
                tab === id
                  ? "bg-violet-600/40 text-white border border-violet-500/40"
                  : "text-white/40 hover:text-white/60 border border-transparent"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}

          {/* Legacy Mode — locked, opens info modal */}
          <button
            onClick={() => setLegacyOpen(true)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium whitespace-nowrap transition-all shrink-0 border"
            style={{
              color: "rgba(251,191,36,0.55)",
              borderColor: "rgba(251,191,36,0.18)",
              background: "rgba(251,191,36,0.04)",
            }}
          >
            <Lock className="w-3 h-3" style={{ color: "rgba(251,191,36,0.5)" }} />
            Legacy Mode
          </button>
        </div>

        {/* Legacy progress indicator */}
        {legacy && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            className="mt-3 rounded-xl px-3.5 py-2.5"
            style={{
              background: "rgba(251,191,36,0.04)",
              border: "1px solid rgba(251,191,36,0.10)",
            }}
          >
            <div className="flex items-center justify-between mb-2">
              <span
                className="text-[10px] font-medium uppercase tracking-wider flex items-center gap-1.5"
                style={{ color: "rgba(251,191,36,0.50)" }}
              >
                <Lock className="w-2.5 h-2.5" />
                Legacy Mode
              </span>
              <span className="text-[10px]" style={{ color: "rgba(251,191,36,0.30)" }}>
                {legacy.unlocked ? "✦ Unlocked" : `${legacy.timeUntil} away`}
              </span>
            </div>

            {/* Progress bar */}
            <div
              className="w-full rounded-full overflow-hidden"
              style={{ height: "3px", background: "rgba(251,191,36,0.10)" }}
            >
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${legacy.progress * 100}%` }}
                transition={{ duration: 1.2, ease: "easeOut", delay: 0.3 }}
                className="h-full rounded-full"
                style={{
                  background: legacy.unlocked
                    ? "rgba(251,191,36,0.9)"
                    : "linear-gradient(90deg, rgba(251,191,36,0.35) 0%, rgba(251,191,36,0.65) 100%)",
                }}
              />
            </div>

            <p className="text-[10px] mt-1.5" style={{ color: "rgba(255,255,255,0.22)" }}>
              {legacy.unlocked
                ? "Legacy Mode is active — your companion has known you for years."
                : `Member for ${legacy.memberFor} · ${legacy.timeUntil} until Legacy`}
            </p>
          </motion.div>
        )}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden">
        <AnimatePresence mode="wait">
          {tab === "bond-score" && (
            <motion.div key="bond-score" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full overflow-y-auto px-5 pb-6">
              <BondScore />
            </motion.div>
          )}
          {tab === "future-memory" && (
            <motion.div key="future-memory" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full overflow-y-auto px-5 pb-6">
              <FutureMemory onStartChat={onStartChat} />
            </motion.div>
          )}
          {tab === "memory" && (
            <motion.div key="memory" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full overflow-y-auto px-5 pb-6">
              <MemoryThreads userId={userId} currentPersona={currentPersona} />
            </motion.div>
          )}
          {tab === "journal" && (
            <motion.div key="journal" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full overflow-y-auto px-5 pb-6">
              <BondJournal userId={userId} currentPersona={currentPersona} />
            </motion.div>
          )}
          {tab === "goals" && (
            <motion.div key="goals" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full overflow-y-auto px-5 pb-6">
              <ConnectionGoals userId={userId} />
            </motion.div>
          )}
          {tab === "roleplay" && (
            <motion.div key="roleplay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full overflow-y-auto px-5 pb-6">
              <RoleplaySimulator />
            </motion.div>
          )}
          {tab === "weekly-insight" && isPremiumHub && (
            <motion.div key="weekly-insight" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full overflow-y-auto px-5 pb-6">
              <WeeklyInsight userId={userId} currentPersona={currentPersona} />
            </motion.div>
          )}
          {tab === "your-profile" && isPowerHub && (
            <motion.div key="your-profile" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full overflow-y-auto px-5 pb-6">
              <PersonalityMap />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Legacy Mode modal */}
      <LegacyModal open={legacyOpen} onClose={() => setLegacyOpen(false)} />
    </motion.div>
  );
}
