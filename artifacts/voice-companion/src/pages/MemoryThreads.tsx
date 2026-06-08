import { useEffect, useState } from "react";
import { Sparkles, Brain } from "lucide-react";
import { apiFetchJSON } from "@/lib/api";
import type { Persona } from "@/lib/api";

const PERSONA_IDS = [
  { id: "companion-aria",  name: "Aria",  color: "rgba(244,114,182,0.6)" },
  { id: "companion-aeva",  name: "Aeva",  color: "rgba(167,139,250,0.6)" },
  { id: "companion-ember", name: "Ember", color: "rgba(251,191,36,0.5)"  },
  { id: "companion-kai",   name: "Kai",   color: "rgba(56,189,248,0.5)"  },
];

interface MemoryRow {
  memory: string;
  created_at?: string;
  timestamp?: string;
  persona_id?: string;
}

interface Thread {
  persona: typeof PERSONA_IDS[number];
  memories: MemoryRow[];
}

interface Props {
  userId: string;
  currentPersona: Persona | null;
}

export function MemoryThreads({ currentPersona }: Props) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all(
      PERSONA_IDS.map(async (p) => {
        try {
          const data = await apiFetchJSON<{ memories: MemoryRow[] }>(
            `/companion/api/memories?persona_id=${p.id}`
          );
          return { persona: p, memories: data.memories ?? [] };
        } catch {
          return { persona: p, memories: [] };
        }
      })
    )
      .then((results) => {
        setThreads(results.filter((t) => t.memories.length > 0));
        setLoading(false);
      })
      .catch(() => { setError("Could not load memories."); setLoading(false); });
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return <p className="text-red-400/70 text-sm text-center py-12">{error}</p>;
  }

  const allEmpty = threads.length === 0;

  return (
    <div className="space-y-6 pt-2">
      <div className="flex items-center gap-2 mb-1">
        <Brain className="w-4 h-4 text-violet-400" />
        <p className="text-white/50 text-xs">
          What BondAI remembers about you and your conversations
        </p>
      </div>

      {allEmpty ? (
        <div className="text-center py-14">
          <Sparkles className="w-8 h-8 text-white/15 mx-auto mb-3" />
          <p className="text-white/30 text-sm">No memories yet.</p>
          <p className="text-white/20 text-xs mt-1">Start chatting to build your memory threads.</p>
        </div>
      ) : (
        threads.map(({ persona, memories }) => (
          <div key={persona.id}>
            {/* Persona header */}
            <div className="flex items-center gap-2 mb-3">
              <div className="w-2 h-2 rounded-full" style={{ background: persona.color }} />
              <span className="text-xs font-semibold text-white/70">{persona.name}</span>
              <span className="text-white/25 text-[10px]">{memories.length} {memories.length === 1 ? "memory" : "memories"}</span>
            </div>

            {/* Memory timeline */}
            <div className="relative pl-4 border-l border-white/08 space-y-3">
              {memories.map((m, i) => {
                const ts = m.created_at ?? m.timestamp;
                const date = ts ? new Date(ts) : null;
                const isHighlighted = currentPersona?.id === persona.id;
                return (
                  <div key={i} className="relative">
                    {/* Dot */}
                    <div
                      className="absolute -left-[17px] top-1.5 w-2 h-2 rounded-full border border-white/20"
                      style={{ background: isHighlighted ? persona.color : "rgba(255,255,255,0.1)" }}
                    />
                    <div
                      className="rounded-xl px-3 py-2.5"
                      style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)" }}
                    >
                      <p className="text-white/80 text-xs leading-relaxed">{m.memory}</p>
                      {date && (
                        <p className="text-white/25 text-[10px] mt-1.5">
                          {date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
