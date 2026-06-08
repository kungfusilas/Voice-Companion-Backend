import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, Sparkles, BookOpen, Target, Activity, CalendarHeart, Lock } from "lucide-react";
import { MemoryThreads } from "./MemoryThreads";
import { BondJournal } from "./BondJournal";
import { ConnectionGoals } from "./ConnectionGoals";
import { BondScore } from "./BondScore";
import { FutureMemory } from "./FutureMemory";
import { LegacyModal } from "@/components/LegacyModal";
import type { Persona } from "@/lib/api";

interface HubProps {
  onBack: () => void;
  userId: string;
  currentPersona: Persona | null;
  onStartChat?: (prompt: string) => void;
}

const LIVE_TABS = [
  { id: "bond-score",    label: "Bond Score",       icon: Activity      },
  { id: "future-memory", label: "Future Memory",    icon: CalendarHeart },
  { id: "memory",        label: "Memory Threads",   icon: Sparkles      },
  { id: "journal",       label: "Bond Journal",     icon: BookOpen      },
  { id: "goals",         label: "Connection Goals", icon: Target        },
] as const;

type Tab = typeof LIVE_TABS[number]["id"];

const BG: React.CSSProperties = {
  background: "linear-gradient(145deg, #0d0d1a 0%, #0f0720 50%, #0d0d1a 100%)",
};

export function Hub({ onBack, userId, currentPersona, onStartChat }: HubProps) {
  const [tab, setTab] = useState<Tab>("bond-score");
  const [legacyOpen, setLegacyOpen] = useState(false);

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
          {LIVE_TABS.map(({ id, label, icon: Icon }) => (
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

          {/* Legacy Mode — locked, premium tab */}
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
        </AnimatePresence>
      </div>

      {/* Legacy Mode modal */}
      <LegacyModal open={legacyOpen} onClose={() => setLegacyOpen(false)} />
    </motion.div>
  );
}
