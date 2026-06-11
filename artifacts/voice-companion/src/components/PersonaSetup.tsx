import { useState } from "react";
import { motion } from "framer-motion";
import { createPersona, type Persona } from "@/lib/api";

interface PersonaSetupProps {
  onCreated: (persona: Persona) => void;
}

const RELATIONSHIP_TYPES = [
  { value: "friend", label: "Friend" },
  { value: "mentor", label: "Mentor" },
  { value: "romantic", label: "Romantic" },
  { value: "coach", label: "Coach" },
  { value: "companion", label: "Companion" },
  { value: "custom", label: "Custom…" },
];

const TRAIT_SUGGESTIONS = [
  "warm", "witty", "curious", "playful", "empathetic",
  "adventurous", "intellectual", "caring", "flirtatious", "mysterious",
];

export function PersonaSetup({ onCreated }: PersonaSetupProps) {
  const [name, setName] = useState("");
  const [relationship, setRelationship] = useState("companion");
  const [customRelationship, setCustomRelationship] = useState("");
  const [traits, setTraits] = useState<string[]>([]);
  const [customTrait, setCustomTrait] = useState("");
  const [backstory, setBackstory] = useState("");
  const [nsfw, setNsfw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const toggleTrait = (t: string) =>
    setTraits((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  const addCustomTrait = () => {
    const t = customTrait.trim().toLowerCase();
    if (t && !traits.includes(t)) {
      setTraits((prev) => [...prev, t]);
      setCustomTrait("");
    }
  };

  const handleCreate = async () => {
    if (!name.trim()) { setError("Please give your companion a name."); return; }
    setError("");
    setLoading(true);
    try {
      const persona = await createPersona({
        name: name.trim(),
        relationship_type: relationship,
        personality_traits: traits,
        backstory,
        custom_relationship: relationship === "custom" ? customRelationship : undefined,
        nsfw_mode: nsfw,
      });
      onCreated(persona);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create persona");
    } finally {
      setLoading(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      className="w-full max-w-md mx-auto flex flex-col gap-5"
    >
      <div className="text-center">
        <h1 className="text-2xl font-bold text-white mb-1">Create Your Companion</h1>
        <p className="text-sm text-white/50">Design your AI companion's personality</p>
      </div>

      {/* Name */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-white/60 uppercase tracking-wider">Name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Luna, Aria, Kai…"
          className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 outline-none focus:ring-2 focus:ring-violet-500/50"
        />
      </div>

      {/* Relationship type */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-white/60 uppercase tracking-wider">Relationship</label>
        <div className="grid grid-cols-3 gap-2">
          {RELATIONSHIP_TYPES.map((r) => (
            <button
              key={r.value}
              onClick={() => setRelationship(r.value)}
              className={`py-2 rounded-lg text-xs font-medium transition border ${
                relationship === r.value
                  ? "bg-violet-600 border-violet-500 text-white"
                  : "bg-white/5 border-white/10 text-white/60 hover:text-white hover:bg-white/10"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
        {relationship === "custom" && (
          <input
            value={customRelationship}
            onChange={(e) => setCustomRelationship(e.target.value)}
            placeholder="Describe the relationship…"
            className="bg-white/5 border border-white/10 rounded-xl px-4 py-2 text-sm text-white placeholder-white/30 outline-none focus:ring-2 focus:ring-violet-500/50"
          />
        )}
      </div>

      {/* Traits */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-white/60 uppercase tracking-wider">Personality Traits</label>
        <div className="flex flex-wrap gap-2">
          {TRAIT_SUGGESTIONS.map((t) => (
            <button
              key={t}
              onClick={() => toggleTrait(t)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition border ${
                traits.includes(t)
                  ? "bg-violet-600 border-violet-500 text-white"
                  : "bg-white/5 border-white/10 text-white/60 hover:text-white hover:bg-white/10"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="flex gap-2 mt-1">
          <input
            value={customTrait}
            onChange={(e) => setCustomTrait(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addCustomTrait()}
            placeholder="Add custom trait…"
            className="flex-1 bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-xs text-white placeholder-white/30 outline-none focus:ring-2 focus:ring-violet-500/50"
          />
          <button
            onClick={addCustomTrait}
            className="px-3 py-2 rounded-xl bg-white/10 text-white/60 text-xs hover:bg-white/20 hover:text-white transition"
          >
            Add
          </button>
        </div>
        {traits.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-1">
            {traits.map((t) => (
              <span
                key={t}
                onClick={() => toggleTrait(t)}
                className="px-2.5 py-0.5 rounded-full bg-violet-800/60 border border-violet-600/40 text-violet-200 text-xs cursor-pointer hover:bg-violet-800"
              >
                {t} ×
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Backstory */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-white/60 uppercase tracking-wider">Backstory (optional)</label>
        <textarea
          value={backstory}
          onChange={(e) => setBackstory(e.target.value)}
          placeholder="Who are they? What's their story?"
          rows={2}
          className="resize-none bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 outline-none focus:ring-2 focus:ring-violet-500/50"
        />
      </div>

      {/* NSFW toggle */}
      <div
        onClick={() => setNsfw((v) => !v)}
        className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition select-none ${
          nsfw
            ? "bg-red-950/40 border-red-800/50"
            : "bg-white/5 border-white/10 hover:bg-white/8"
        }`}
      >
        <div
          className={`w-9 h-5 rounded-full relative transition-colors ${nsfw ? "bg-red-600" : "bg-white/20"}`}
        >
          <motion.div
            className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow"
            animate={{ left: nsfw ? "calc(100% - 18px)" : "2px" }}
            transition={{ type: "spring", stiffness: 500, damping: 30 }}
          />
        </div>
        <div>
          <p className={`text-sm font-medium ${nsfw ? "text-red-300" : "text-white/70"}`}>
            Adult mode (18+)
          </p>
          <p className="text-xs text-white/35">Uses advanced AI for uncensored conversations</p>
        </div>
      </div>

      {error && <p className="text-xs text-red-400 text-center">{error}</p>}

      <motion.button
        onClick={handleCreate}
        disabled={loading}
        whileTap={{ scale: 0.97 }}
        className="py-3 rounded-xl font-semibold text-sm text-white transition disabled:opacity-50 disabled:cursor-not-allowed"
        style={{
          background: "linear-gradient(135deg, #6d28d9, #7c3aed)",
          boxShadow: "0 4px 20px rgba(109,40,217,0.4)",
        }}
      >
        {loading ? "Creating…" : "Start Conversation →"}
      </motion.button>
    </motion.div>
  );
}
