import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, Sparkles, BookOpen, Target, Star, BarChart2, Shield, PlayCircle } from "lucide-react";
import { MemoryThreads } from "./MemoryThreads";
import { BondJournal } from "./BondJournal";
import { ConnectionGoals } from "./ConnectionGoals";
import type { Persona } from "@/lib/api";

interface HubProps {
  onBack: () => void;
  userId: string;
  currentPersona: Persona | null;
}

const LIVE_TABS = [
  { id: "memory", label: "Memory Threads", icon: Sparkles },
  { id: "journal", label: "Bond Journal",   icon: BookOpen  },
  { id: "goals",  label: "Connection Goals", icon: Target  },
] as const;

const COMING_SOON = [
  { label: "Bond Score",           icon: Star,       desc: "Communication effectiveness rating" },
  { label: "Relationship Insights",icon: BarChart2,  desc: "Pattern analysis across conversations" },
  { label: "Trust Meter",          icon: Shield,     desc: "Measures consistency and engagement" },
  { label: "Conversation Replay",  icon: PlayCircle, desc: "Review important interactions" },
];

type Tab = typeof LIVE_TABS[number]["id"];

const BG: React.CSSProperties = {
  background: "linear-gradient(145deg, #0d0d1a 0%, #0f0720 50%, #0d0d1a 100%)",
};

export function Hub({ onBack, userId, currentPersona }: HubProps) {
  const [tab, setTab] = useState<Tab>("memory");

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
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden">
        <AnimatePresence mode="wait">
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

      {/* Coming Soon section */}
      <div className="shrink-0 px-5 pb-8">
        <p className="text-white/25 text-[10px] uppercase tracking-widest mb-3 font-medium">Coming Soon</p>
        <div className="grid grid-cols-2 gap-2">
          {COMING_SOON.map(({ label, icon: Icon, desc }) => (
            <div
              key={label}
              className="flex flex-col gap-1.5 rounded-xl p-3 border border-white/06"
              style={{ background: "rgba(255,255,255,0.02)" }}
            >
              <div className="flex items-center gap-2">
                <Icon className="w-3.5 h-3.5 text-white/20" />
                <span className="text-white/35 text-xs font-medium">{label}</span>
                <span className="ml-auto text-[9px] px-1.5 py-0.5 rounded-full bg-violet-900/40 text-violet-400/60 border border-violet-700/30">Soon</span>
              </div>
              <p className="text-white/20 text-[10px] leading-snug">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    </motion.div>
  );
}
