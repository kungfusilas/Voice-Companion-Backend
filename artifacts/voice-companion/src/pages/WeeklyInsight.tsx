import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { BarChart2, Loader2, RefreshCw, TrendingUp, Hash, Zap, MessageSquare } from "lucide-react";
import type { Persona } from "@/lib/api";

const BASE = "/companion";

async function apiFetch(url: string, opts?: RequestInit): Promise<Response> {
  const token = (await import("@/lib/supabase")).supabase.auth.getSession().then(
    (r) => r.data.session?.access_token ?? ""
  );
  const t = await token;
  return fetch(url, {
    ...opts,
    headers: {
      ...(opts?.headers ?? {}),
      ...(t ? { Authorization: `Bearer ${t}` } : {}),
    },
  });
}

interface Report {
  emotional_themes?: string[];
  top_topics?: string[];
  mood_arc?: string | null;
  pattern?: string | null;
  closing_note?: string | null;
  week_start?: string;
  empty?: boolean;
}

interface WeeklyInsightProps {
  userId: string;
  currentPersona: Persona | null;
}

function formatWeekStart(iso: string | undefined): string {
  if (!iso) return "This week";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
}

const THEME_COLORS = [
  "rgba(139,92,246,0.15)",
  "rgba(236,72,153,0.15)",
  "rgba(34,211,238,0.12)",
  "rgba(251,191,36,0.12)",
  "rgba(52,211,153,0.12)",
];
const THEME_BORDERS = [
  "rgba(139,92,246,0.30)",
  "rgba(236,72,153,0.30)",
  "rgba(34,211,238,0.25)",
  "rgba(251,191,36,0.25)",
  "rgba(52,211,153,0.25)",
];
const THEME_TEXT = [
  "rgba(167,139,250,0.9)",
  "rgba(244,114,182,0.9)",
  "rgba(103,232,249,0.9)",
  "rgba(253,224,71,0.9)",
  "rgba(110,231,183,0.9)",
];

export function WeeklyInsight({ userId: _userId, currentPersona }: WeeklyInsightProps) {
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const companionId = currentPersona?.id ?? "aria";

  const fetchReport = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch(`${BASE}/api/reports/weekly?companion_id=${companionId}`);
      if (resp.ok) {
        const data = await resp.json();
        setReport(data.report ?? null);
      }
    } catch {
      setError("Couldn't load your report.");
    } finally {
      setLoading(false);
    }
  };

  const generateReport = async () => {
    setGenerating(true);
    setError(null);
    try {
      const resp = await apiFetch(
        `${BASE}/api/reports/weekly/generate?companion_id=${companionId}`,
        { method: "POST" }
      );
      if (resp.ok) {
        const data = await resp.json();
        setReport(data.report ?? null);
      } else {
        setError("Couldn't generate your report. Try again.");
      }
    } catch {
      setError("Couldn't generate your report. Try again.");
    } finally {
      setGenerating(false);
    }
  };

  useEffect(() => {
    fetchReport();
  }, [companionId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-5 h-5 text-violet-400 animate-spin" />
      </div>
    );
  }

  if (!report) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col items-center text-center py-16 px-4"
      >
        <div
          className="w-14 h-14 rounded-2xl flex items-center justify-center mb-4"
          style={{ background: "rgba(139,92,246,0.12)", border: "1px solid rgba(139,92,246,0.25)" }}
        >
          <BarChart2 className="w-6 h-6 text-violet-400" />
        </div>
        <h3 className="text-white text-sm font-semibold mb-2">No report yet this week</h3>
        <p className="text-white/35 text-xs leading-relaxed mb-6 max-w-xs">
          Your Weekly Insight is generated from your conversations. Generate one now to see your emotional themes,
          patterns, and a personal note from {currentPersona?.name ?? "your companion"}.
        </p>
        {error && <p className="text-red-400 text-xs mb-4">{error}</p>}
        <button
          onClick={generateReport}
          disabled={generating}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-white transition disabled:opacity-50"
          style={{
            background: "linear-gradient(135deg, #7c3aed, #6d28d9)",
            boxShadow: "0 4px 16px rgba(124,58,237,0.3)",
          }}
        >
          {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart2 className="w-4 h-4" />}
          {generating ? "Generating…" : "Generate This Week's Report"}
        </button>
      </motion.div>
    );
  }

  const themes = report.emotional_themes ?? [];
  const topics = report.top_topics ?? [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-4 pt-2 pb-8"
    >
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wider text-white/30">Week of</p>
          <p className="text-white/70 text-xs font-medium mt-0.5">{formatWeekStart(report.week_start)}</p>
        </div>
        <button
          onClick={generateReport}
          disabled={generating}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-white/50 hover:text-white/80 transition border border-white/10 disabled:opacity-40"
          title="Regenerate this week's report"
        >
          <RefreshCw className={`w-3 h-3 ${generating ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Emotional themes */}
      {themes.length > 0 && (
        <div
          className="rounded-2xl p-4"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
        >
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className="w-3.5 h-3.5 text-violet-400" />
            <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">Emotional themes</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <AnimatePresence>
              {themes.map((t, i) => (
                <motion.span
                  key={t}
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: i * 0.05 }}
                  className="px-2.5 py-1 rounded-full text-[11px] font-medium"
                  style={{
                    background: THEME_COLORS[i % THEME_COLORS.length],
                    border: `1px solid ${THEME_BORDERS[i % THEME_BORDERS.length]}`,
                    color: THEME_TEXT[i % THEME_TEXT.length],
                  }}
                >
                  {t}
                </motion.span>
              ))}
            </AnimatePresence>
          </div>
        </div>
      )}

      {/* Top topics */}
      {topics.length > 0 && (
        <div
          className="rounded-2xl p-4"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
        >
          <div className="flex items-center gap-2 mb-3">
            <Hash className="w-3.5 h-3.5 text-rose-400" />
            <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">Top topics</p>
          </div>
          <ul className="space-y-1.5">
            {topics.map((t, i) => (
              <li key={t} className="flex items-center gap-2 text-xs text-white/60">
                <span
                  className="w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold shrink-0"
                  style={{ background: "rgba(244,114,182,0.15)", color: "rgba(244,114,182,0.8)" }}
                >
                  {i + 1}
                </span>
                {t}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Mood arc */}
      {report.mood_arc && (
        <div
          className="rounded-2xl p-4"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
        >
          <div className="flex items-center gap-2 mb-2">
            <Zap className="w-3.5 h-3.5 text-amber-400" />
            <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">Mood arc</p>
          </div>
          <p className="text-white/65 text-xs leading-relaxed">{report.mood_arc}</p>
        </div>
      )}

      {/* Pattern noticed */}
      {report.pattern && (
        <div
          className="rounded-2xl p-4"
          style={{
            background: "rgba(34,211,238,0.05)",
            border: "1px solid rgba(34,211,238,0.15)",
          }}
        >
          <p className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "rgba(103,232,249,0.6)" }}>
            Pattern noticed
          </p>
          <p className="text-xs leading-relaxed" style={{ color: "rgba(103,232,249,0.85)" }}>
            {report.pattern}
          </p>
        </div>
      )}

      {/* Closing note */}
      {report.closing_note && (
        <div
          className="rounded-2xl p-4"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
        >
          <div className="flex items-center gap-2 mb-2">
            <MessageSquare className="w-3.5 h-3.5 text-emerald-400" />
            <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
              A note from {currentPersona?.name ?? "your companion"}
            </p>
          </div>
          <p className="text-white/55 text-xs leading-relaxed italic">{report.closing_note}</p>
        </div>
      )}

      {error && <p className="text-red-400 text-xs text-center">{error}</p>}
    </motion.div>
  );
}
