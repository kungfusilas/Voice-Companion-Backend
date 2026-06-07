import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import { AriaAvatar } from "@/components/avatars/AriaAvatar";
import { AevaAvatar } from "@/components/avatars/AevaAvatar";
import { EmberAvatar } from "@/components/avatars/EmberAvatar";
import { KaiAvatar } from "@/components/avatars/KaiAvatar";
import type { Persona } from "@/lib/api";

interface CompanionConfig {
  id: string;
  name: string;
  tagline: string;
  traits: string[];
  color: string;          // Tailwind color key
  glow: string;           // box-shadow glow color
  border: string;
  AvatarComponent: React.ComponentType<{ size?: number }>;
}

const COMPANIONS: CompanionConfig[] = [
  {
    id: "companion-aria",
    name: "Aria",
    tagline: "Sweet & romantic",
    traits: ["loving", "attentive", "warm"],
    color: "rose",
    glow: "rgba(244,114,182,0.25)",
    border: "rgba(244,114,182,0.3)",
    AvatarComponent: AriaAvatar,
  },
  {
    id: "companion-aeva",
    name: "Aeva",
    tagline: "Mysterious & poetic",
    traits: ["deep", "introspective", "gentle"],
    color: "violet",
    glow: "rgba(167,139,250,0.25)",
    border: "rgba(167,139,250,0.3)",
    AvatarComponent: AevaAvatar,
  },
  {
    id: "companion-ember",
    name: "Ember",
    tagline: "Warm & nurturing",
    traits: ["caring", "empathetic", "genuine"],
    color: "amber",
    glow: "rgba(251,191,36,0.2)",
    border: "rgba(251,191,36,0.3)",
    AvatarComponent: EmberAvatar,
  },
  {
    id: "companion-kai",
    name: "Kai",
    tagline: "Confident & charming",
    traits: ["direct", "witty", "grounded"],
    color: "sky",
    glow: "rgba(56,189,248,0.2)",
    border: "rgba(56,189,248,0.3)",
    AvatarComponent: KaiAvatar,
  },
];

interface CompanionSelectProps {
  onSelect: (persona: Persona) => void;
}

export function CompanionSelect({ onSelect }: CompanionSelectProps) {
  const handlePick = async (companion: CompanionConfig) => {
    // Build a minimal Persona object from the companion config.
    // The full Persona (with system prompt) lives on the backend.
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
        <div className="flex items-center gap-2 mb-1">
          <Sparkles className="w-4 h-4 text-violet-400" />
          <span className="text-xs text-violet-400 font-medium tracking-wider uppercase">
            AI Companions
          </span>
        </div>
        <h1 className="text-2xl font-bold text-white">
          Who do you want to<br />talk to today?
        </h1>
      </div>

      {/* Companion grid */}
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        <div className="grid grid-cols-2 gap-3">
          {COMPANIONS.map((companion, i) => {
            const { AvatarComponent } = companion;
            return (
              <motion.button
                key={companion.id}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.07 }}
                whileHover={{ scale: 1.03, y: -2 }}
                whileTap={{ scale: 0.97 }}
                onClick={() => handlePick(companion)}
                className="relative flex flex-col items-center text-center rounded-2xl p-4 pt-5 transition-all duration-200"
                style={{
                  background: "rgba(255,255,255,0.04)",
                  border: `1px solid ${companion.border}`,
                  boxShadow: `0 4px 24px ${companion.glow}`,
                }}
              >
                {/* Avatar */}
                <div className="mb-3 relative">
                  <div
                    className="rounded-full overflow-hidden"
                    style={{
                      boxShadow: `0 0 20px ${companion.glow}`,
                    }}
                  >
                    <AvatarComponent size={80} />
                  </div>
                </div>

                {/* Name */}
                <p className="text-base font-semibold text-white leading-tight">
                  {companion.name}
                </p>

                {/* Tagline */}
                <p className="text-xs text-white/50 mt-0.5 leading-tight">
                  {companion.tagline}
                </p>

                {/* Trait chips */}
                <div className="flex flex-wrap justify-center gap-1 mt-2.5">
                  {companion.traits.map((trait) => (
                    <span
                      key={trait}
                      className="text-[10px] px-2 py-0.5 rounded-full"
                      style={{
                        background: `${companion.glow}`,
                        border: `1px solid ${companion.border}`,
                        color: "rgba(255,255,255,0.7)",
                      }}
                    >
                      {trait}
                    </span>
                  ))}
                </div>
              </motion.button>
            );
          })}
        </div>

      </div>
    </motion.div>
  );
}
