import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Loader2, MessageSquare, ChevronDown, ChevronUp, Sparkles, TrendingUp } from "lucide-react";
import { supabase } from "@/lib/supabase";

const BASE = "/companion";

async function apiFetch(url: string, opts?: RequestInit) {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token ?? "";
  return fetch(url, {
    ...opts,
    headers: { ...(opts?.headers ?? {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
}

interface DebriefMetrics {
  negative_self_talk?: number;
  deflected_questions?: number;
  opened_up_moments?: number;
  humor_as_deflection?: number;
  emotional_openness_score?: number;
}

interface DebriefData {
  session_id?: string;
  companion_name?: string;
  message_count?: number;
  metrics?: DebriefMetrics;
  patterns?: string[];
  companion_note?: string;
  highlight?: string;
  created_at?: string;
}

interface DebriefRow {
  id: string;
  created_at: string;
  companion_id?: string;
  debrief: DebriefData;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function MetricBar({ label, value, max = 10, color }: { label: string; value: number; max?: number; color: string }) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <p className="text-[11px] text-white/50">{label}</p>
        <p className="text-[11px] font-medium text-white/70">{value}{max !== 10 ? "" : "/10"}</p>
      </div>
      <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className="h-full rounded-full"
          style={{ background: color }}
        />
      </div>
    </div>
  );
}

function DebriefCard({ row, defaultOpen = false }: { row: DebriefRow; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const d = row.debrief;
  const m = d.metrics ?? {};

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
    >
      <button
        className="w-full flex items-center justify-between px-4 py-3"
        onClick={() => setOpen(v => !v)}
      >
        <div className="flex items-center gap-2.5 text-left">
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: "rgba(139,92,246,0.12)", border: "1px solid rgba(139,92,246,0.25)" }}
          >
            <MessageSquare className="w-3.5 h-3.5 text-violet-400" />
          </div>
          <div>
            <p className="text-xs font-medium text-white/80">
              {d.companion_name ? `With ${d.companion_name}` : "Session"} · {d.message_count ?? "?"} messages
            </p>
            <p className="text-[10px] text-white/30 mt-0.5">{formatDate(row.created_at)}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {typeof m.emotional_openness_score === "number" && (
            <span
              className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
              style={{
                background: m.emotional_openness_score >= 7 ? "rgba(52,211,153,0.12)" : "rgba(251,191,36,0.12)",
                color: m.emotional_openness_score >= 7 ? "rgba(52,211,153,0.8)" : "rgba(251,191,36,0.8)",
              }}
            >
              {m.emotional_openness_score}/10
            </span>
          )}
          {open ? <ChevronUp className="w-3.5 h-3.5 text-white/30" /> : <ChevronDown className="w-3.5 h-3.5 text-white/30" />}
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 space-y-4 border-t border-white/5 pt-3">
              {/* Metrics */}
              <div className="space-y-2.5">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-white/30">Behavioral Metrics</p>
                {typeof m.emotional_openness_score === "number" && (
                  <MetricBar label="Emotional Openness" value={m.emotional_openness_score} max={10} color="rgba(139,92,246,0.7)" />
                )}
                {typeof m.opened_up_moments === "number" && m.opened_up_moments > 0 && (
                  <MetricBar label="Opened Up" value={m.opened_up_moments} max={Math.max(m.opened_up_moments, 5)} color="rgba(52,211,153,0.7)" />
                )}
                {typeof m.deflected_questions === "number" && m.deflected_questions > 0 && (
                  <MetricBar label="Deflected Questions" value={m.deflected_questions} max={Math.max(m.deflected_questions, 5)} color="rgba(251,191,36,0.7)" />
                )}
                {typeof m.negative_self_talk === "number" && m.negative_self_talk > 0 && (
                  <MetricBar label="Negative Self-Talk" value={m.negative_self_talk} max={Math.max(m.negative_self_talk, 5)} color="rgba(251,113,133,0.7)" />
                )}
                {typeof m.humor_as_deflection === "number" && m.humor_as_deflection > 0 && (
                  <MetricBar label="Humor as Deflection" value={m.humor_as_deflection} max={Math.max(m.humor_as_deflection, 5)} color="rgba(251,191,36,0.5)" />
                )}
              </div>

              {/* Patterns */}
              {d.patterns && d.patterns.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 mb-2">
                    <TrendingUp className="w-3 h-3 text-violet-400/60" />
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-white/30">Patterns Noticed</p>
                  </div>
                  <ul className="space-y-1.5">
                    {d.patterns.map((p, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-white/50 leading-relaxed">
                        <span className="mt-1.5 w-1 h-1 rounded-full bg-violet-400/40 shrink-0" />
                        {p}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Highlight */}
              {d.highlight && (
                <div
                  className="rounded-xl px-3 py-2.5"
                  style={{ background: "rgba(52,211,153,0.06)", border: "1px solid rgba(52,211,153,0.12)" }}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <Sparkles className="w-3 h-3 text-emerald-400/70" />
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-400/50">Highlight</p>
                  </div>
                  <p className="text-xs text-white/55 leading-relaxed">{d.highlight}</p>
                </div>
              )}

              {/* Companion note */}
              {d.companion_note && (
                <div
                  className="rounded-xl px-3 py-2.5"
                  style={{ background: "rgba(139,92,246,0.06)", border: "1px solid rgba(139,92,246,0.12)" }}
                >
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-violet-400/50 mb-1">
                    {d.companion_name ?? "Companion"} says
                  </p>
                  <p className="text-xs text-white/55 italic leading-relaxed">"{d.companion_note}"</p>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function ConversationDebrief() {
  const [rows, setRows] = useState<DebriefRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const resp = await apiFetch(`${BASE}/api/analysis/debriefs`);
        if (resp.ok) {
          const data = await resp.json();
          setRows(data.debriefs ?? []);
        } else if (resp.status === 403) {
          setError("Power tier required to access Communication Analysis.");
        } else {
          setError("Couldn't load your debriefs.");
        }
      } catch {
        setError("Couldn't load your debriefs.");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-5 h-5 text-violet-400 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center text-center py-16 px-4">
        <MessageSquare className="w-8 h-8 text-white/20 mb-3" />
        <p className="text-white/40 text-sm">{error}</p>
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center text-center py-16 px-4">
        <div
          className="w-12 h-12 rounded-2xl flex items-center justify-center mb-4"
          style={{ background: "rgba(139,92,246,0.10)", border: "1px solid rgba(139,92,246,0.20)" }}
        >
          <MessageSquare className="w-5 h-5 text-violet-400/60" />
        </div>
        <p className="text-white/60 text-sm font-medium mb-1">No debriefs yet</p>
        <p className="text-white/30 text-xs leading-relaxed max-w-xs">
          After each chat session, a behavioral analysis will appear here automatically — no action needed.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3 pt-2 pb-8">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-white/30 mb-3">
        {rows.length} session{rows.length !== 1 ? "s" : ""} analyzed
      </p>
      {rows.map((row, i) => (
        <DebriefCard key={row.id} row={row} defaultOpen={i === 0} />
      ))}
    </div>
  );
}
