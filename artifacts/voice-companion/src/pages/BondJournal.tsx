import { useEffect, useState } from "react";
import { BookOpen } from "lucide-react";
import { apiFetchJSON } from "@/lib/api";
import type { Persona } from "@/lib/api";

const PERSONA_IDS = [
  { id: "companion-aria",  name: "Aria"  },
  { id: "companion-aeva",  name: "Aeva"  },
  { id: "companion-ember", name: "Ember" },
  { id: "companion-kai",   name: "Kai"   },
];

interface MemoryRow {
  memory: string;
  created_at?: string;
  timestamp?: string;
}

interface JournalEntry {
  date: string;         // ISO date string "2024-01-15"
  dateLabel: string;    // "Jan 15, 2024"
  personaName: string;
  snippets: string[];
}

interface Props {
  userId: string;
  currentPersona: Persona | null;
}

function toDateKey(ts: string): string {
  return new Date(ts).toISOString().split("T")[0];
}

function toDateLabel(key: string): string {
  return new Date(key + "T12:00:00").toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric", year: "numeric",
  });
}

export function BondJournal({ currentPersona }: Props) {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
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
          return { name: p.name, memories: data.memories ?? [] };
        } catch {
          return { name: p.name, memories: [] };
        }
      })
    )
      .then((results) => {
        // Build journal entries: group memories by (date, persona)
        const map: Record<string, JournalEntry> = {};
        for (const { name, memories } of results) {
          for (const m of memories) {
            const ts = m.created_at ?? m.timestamp;
            if (!ts) continue;
            const key = `${toDateKey(ts)}__${name}`;
            if (!map[key]) {
              map[key] = {
                date: toDateKey(ts),
                dateLabel: toDateLabel(toDateKey(ts)),
                personaName: name,
                snippets: [],
              };
            }
            map[key].snippets.push(m.memory);
          }
        }
        const sorted = Object.values(map).sort((a, b) => b.date.localeCompare(a.date));
        setEntries(sorted);
        setLoading(false);
      })
      .catch(() => { setError("Could not load journal."); setLoading(false); });
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

  return (
    <div className="space-y-4 pt-2">
      <div className="flex items-center gap-2 mb-1">
        <BookOpen className="w-4 h-4 text-violet-400" />
        <p className="text-white/50 text-xs">
          An auto-generated log of your conversations
        </p>
      </div>

      {entries.length === 0 ? (
        <div className="text-center py-14">
          <BookOpen className="w-8 h-8 text-white/15 mx-auto mb-3" />
          <p className="text-white/30 text-sm">No journal entries yet.</p>
          <p className="text-white/20 text-xs mt-1">Your conversations will appear here as you chat.</p>
        </div>
      ) : (
        entries.map((entry, i) => (
          <div
            key={i}
            className="rounded-2xl p-4"
            style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
          >
            {/* Date + persona */}
            <div className="flex items-center justify-between mb-3">
              <span className="text-white/60 text-xs font-medium">{entry.dateLabel}</span>
              <span
                className="text-[10px] px-2 py-0.5 rounded-full"
                style={{ background: "rgba(139,92,246,0.15)", border: "1px solid rgba(139,92,246,0.25)", color: "rgba(196,181,253,0.8)" }}
              >
                with {entry.personaName}
                {currentPersona?.name === entry.personaName ? " · active" : ""}
              </span>
            </div>

            {/* Snippets */}
            <div className="space-y-2">
              {entry.snippets.map((s, j) => (
                <div key={j} className="flex gap-2">
                  <span className="text-violet-400/50 text-xs mt-0.5 shrink-0">—</span>
                  <p className="text-white/65 text-xs leading-relaxed">{s}</p>
                </div>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
