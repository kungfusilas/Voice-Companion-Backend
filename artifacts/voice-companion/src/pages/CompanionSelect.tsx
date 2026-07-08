import { motion } from "framer-motion";
import { Sparkles, LogOut, LayoutGrid } from "lucide-react";
import type { Persona } from "@/lib/api";
import { PromoVideo } from "@/components/PromoVideo";

interface CompanionConfig {
  id: string;
  name: string;
  tagline: string;
  traits: string[];
  glow: string;
  border: string;
  avatar: string;
}

const COMPANIONS: CompanionConfig[] = [
  {
    id: "companion-aeva",
    name: "Aeva",
    tagline: "Confident & a little possessive",
    traits: ["expressive", "jealous", "needy"],
    glow: "rgba(167,139,250,0.25)",
    border: "rgba(167,139,250,0.3)",
    avatar: "/companion/avatars/aeva.jpg",
  },
  {
    id: "companion-kai",
    name: "Kai",
    tagline: "Confident & charming",
    traits: ["direct", "witty", "grounded"],
    glow: "rgba(56,189,248,0.2)",
    border: "rgba(56,189,248,0.3)",
    avatar: "/companion/avatars/kai.jpg",
  },
];

interface CompanionSelectProps {
  onSelect: (persona: Persona) => void;
  onSignOut?: () => void;
  onSignIn?: () => void;
  onUpgrade?: () => void;
  onHub?: () => void;
  subscriptionTier?: string;
}

export function CompanionSelect({ onSelect, onSignOut, onSignIn, onUpgrade, onHub, subscriptionTier }: CompanionSelectProps) {
  const handlePick = (companion: CompanionConfig) => {
    const persona: Persona = {
      id: companion.id,
      name: companion.name,
      relationship_type: "companion",
      personality_traits: companion.traits,
      backstory: "",
      custom_relationship: "",
      voice_id: null,
      nsfw_mode: false,
    };
    onSelect(persona);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      className="flex flex-col h-full"
    >
      {/* Header */}
      <div className="px-6 pt-6 pb-4 shrink-0">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-violet-400" />
            <span className="text-xs text-violet-400 font-medium tracking-wider uppercase">
              AI Companions
            </span>
          </div>
          <div className="flex items-center gap-2">
            {onHub && (
              <button
                onClick={onHub}
                title="LegacyBond AI Features"
                className="flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full border border-violet-500/30 text-violet-400/80 hover:text-violet-300 hover:border-violet-400/50 transition-colors"
              >
                <LayoutGrid className="w-3 h-3" />
                Features
              </button>
            )}
            {onUpgrade && (
              <button
                onClick={onUpgrade}
                className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-full border border-violet-500/30 text-violet-400/80 hover:text-violet-300 hover:border-violet-400/50 transition-colors capitalize"
              >
                {subscriptionTier && subscriptionTier !== "free" ? subscriptionTier : "Plans"}
              </button>
            )}
            {!onSignOut && onSignIn && (
              <button
                onClick={onSignIn}
                className="flex items-center gap-1 text-[11px] px-3 py-1.5 rounded-full font-semibold transition-colors text-white"
                style={{
                  background: "linear-gradient(135deg, #7c3aed, #6d28d9)",
                  boxShadow: "0 2px 8px rgba(124,58,237,0.35)",
                }}
              >
                Log in
              </button>
            )}
            {onSignOut && (
              <button
                onClick={onSignOut}
                title="Sign out"
                className="flex items-center gap-1.5 text-white/30 hover:text-white/60 transition-colors text-xs"
              >
                <LogOut className="w-3.5 h-3.5" />
                <span>Sign out</span>
              </button>
            )}
          </div>
        </div>
        <h1 className="text-2xl font-bold text-white">
          Who do you want to<br />talk to today?
        </h1>
      </div>

      {/* Promo video */}
      <PromoVideo />

      {/* Companion grid */}
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        <div className="grid grid-cols-2 gap-3">
          {COMPANIONS.map((companion, i) => (
            <motion.button
              key={companion.id}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.07 }}
              whileHover={{ scale: 1.03, y: -2 }}
              whileTap={{ scale: 0.97 }}
              onClick={() => handlePick(companion)}
              className="relative flex flex-col items-stretch text-center rounded-2xl overflow-hidden transition-all duration-200"
              style={{
                background: "rgba(255,255,255,0.04)",
                border: `1px solid ${companion.border}`,
                boxShadow: `0 4px 24px ${companion.glow}`,
              }}
            >
              {/* Portrait image */}
              <img
                src={companion.avatar}
                alt={companion.name}
                style={{
                  width: "100%",
                  height: 200,
                  objectFit: "cover",
                  objectPosition: "center top",
                  borderRadius: "14px 14px 0 0",
                  display: "block",
                }}
              />

              {/* Info section */}
              <div className="px-3 py-3 flex flex-col items-center">
                {/* Name */}
                <p className="text-base font-semibold text-white leading-tight">
                  {companion.name}
                </p>
              </div>
            </motion.button>
          ))}
        </div>
      </div>
    </motion.div>
  );
}
