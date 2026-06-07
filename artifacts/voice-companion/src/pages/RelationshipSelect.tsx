import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, Loader2 } from "lucide-react";
import { setRelationshipType } from "@/lib/api";
import type { Persona } from "@/lib/api";

interface RelType {
  id: string;
  emoji: string;
  label: string;
  description: string;
  glow: string;
  border: string;
  textColor: string;
}

const REL_TYPES: RelType[] = [
  {
    id: "romance",
    emoji: "💕",
    label: "Romance",
    description: "Something more than friends",
    glow: "rgba(244,63,94,0.2)",
    border: "rgba(244,63,94,0.4)",
    textColor: "#fb7185",
  },
  {
    id: "mentor",
    emoji: "🧠",
    label: "Mentor",
    description: "Guide me, challenge me",
    glow: "rgba(139,92,246,0.2)",
    border: "rgba(139,92,246,0.4)",
    textColor: "#a78bfa",
  },
  {
    id: "friendship",
    emoji: "🤝",
    label: "Friendship",
    description: "Just good company",
    glow: "rgba(20,184,166,0.2)",
    border: "rgba(20,184,166,0.4)",
    textColor: "#2dd4bf",
  },
  {
    id: "professional",
    emoji: "💼",
    label: "Professional",
    description: "Keep it productive",
    glow: "rgba(56,189,248,0.2)",
    border: "rgba(56,189,248,0.4)",
    textColor: "#38bdf8",
  },
];

interface RelationshipSelectProps {
  persona: Persona;
  userId: string;
  onSelect: (relType: string) => void;
  onBack: () => void;
}

export function RelationshipSelect({ persona, userId, onSelect, onBack }: RelationshipSelectProps) {
  const [saving, setSaving] = useState<string | null>(null);

  const handlePick = async (rt: RelType) => {
    if (saving) return;
    setSaving(rt.id);
    try {
      await setRelationshipType(userId, persona.id, rt.id);
      onSelect(rt.id);
    } catch {
      setSaving(null);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: 30 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -30 }}
      className="flex flex-col h-full"
    >
      {/* Header */}
      <div className="px-4 pt-4 pb-2 shrink-0">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-white/50 hover:text-white transition text-sm mb-4"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>

        {/* Companion mini-card */}
        <div className="flex items-center gap-3 mb-5">
          <img
            src={`/companion/avatars/${persona.id.replace("companion-", "")}.jpg`}
            alt={persona.name}
            className="w-12 h-12 rounded-full object-cover object-top"
            style={{ border: "1px solid rgba(255,255,255,0.15)" }}
          />
          <div>
            <p className="text-white font-semibold">{persona.name}</p>
            <p className="text-white/40 text-xs">How do you want to connect?</p>
          </div>
        </div>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto px-4 pb-6">
        <div className="grid grid-cols-2 gap-3">
          {REL_TYPES.map((rt, i) => (
            <motion.button
              key={rt.id}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.07 }}
              whileHover={{ scale: 1.03, y: -2 }}
              whileTap={{ scale: 0.97 }}
              onClick={() => handlePick(rt)}
              disabled={!!saving}
              className="relative flex flex-col items-center justify-center text-center rounded-2xl p-5 transition-all disabled:opacity-60"
              style={{
                background: "rgba(255,255,255,0.04)",
                border: `1px solid ${rt.border}`,
                boxShadow: `0 4px 24px ${rt.glow}`,
                minHeight: 130,
              }}
            >
              {saving === rt.id ? (
                <Loader2 className="w-6 h-6 animate-spin mb-2" style={{ color: rt.textColor }} />
              ) : (
                <span className="text-3xl mb-2">{rt.emoji}</span>
              )}
              <p className="font-semibold text-white text-sm">{rt.label}</p>
              <p className="text-xs mt-1" style={{ color: rt.textColor, opacity: 0.8 }}>
                {rt.description}
              </p>
            </motion.button>
          ))}
        </div>

        <p className="text-center text-white/25 text-[11px] mt-6 px-4">
          You can always start over by going back and picking a different companion.
        </p>
      </div>
    </motion.div>
  );
}
