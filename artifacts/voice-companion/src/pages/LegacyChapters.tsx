import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ScrollText, Loader2, Download, ChevronRight, Lock, Sparkles, RefreshCw } from "lucide-react";
import type { Persona } from "@/lib/api";

const BASE = "/companion";

async function apiFetch(url: string, opts?: RequestInit): Promise<Response> {
  const token = await (await import("@/lib/supabase")).supabase.auth
    .getSession()
    .then((r) => r.data.session?.access_token ?? "");
  return fetch(url, {
    ...opts,
    headers: { ...(opts?.headers ?? {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
}

interface Chapter {
  id: string;
  period_month: string;
  title: string;
  content?: string;
  created_at?: string;
}

interface LegacyChaptersProps {
  userId: string;
  currentPersona: Persona | null;
  isPower: boolean;
}

function formatPeriod(period: string): string {
  try {
    const [y, m] = period.split("-");
    return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString("en-US", {
      month: "long",
      year: "numeric",
    });
  } catch {
    return period;
  }
}

function currentPeriod(): string {
  const now = new Date();
  const y = now.getUTCFullYear();
  const m = String(now.getUTCMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function LockedTeaser() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center text-center py-16 px-6"
    >
      <div
        className="w-16 h-16 rounded-2xl flex items-center justify-center mb-5"
        style={{ background: "rgba(217,119,6,0.10)", border: "1px solid rgba(217,119,6,0.25)" }}
      >
        <Lock className="w-7 h-7" style={{ color: "rgba(251,191,36,0.7)" }} />
      </div>
      <h3 className="text-white text-sm font-semibold mb-2">Legacy Chapters</h3>
      <p className="text-white/40 text-xs leading-relaxed max-w-xs mb-3">
        Every month on Power, your companion writes a polished narrative chapter of your life
        — drawn from your conversations, memories, and milestones. Your story, chapter by chapter.
      </p>
      <p className="text-[11px] font-medium" style={{ color: "rgba(251,191,36,0.55)" }}>
        Power plan only
      </p>
    </motion.div>
  );
}

interface ChapterDetailProps {
  chapter: Chapter;
  onBack: () => void;
}

function ChapterDetail({ chapter, onBack }: ChapterDetailProps) {
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const resp = await apiFetch(
        `${BASE}/api/legacy-chapters/${chapter.id}/download?format=txt`
      );
      if (resp.ok) {
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `legacy-chapter-${chapter.period_month}.txt`;
        a.click();
        URL.revokeObjectURL(url);
      }
    } finally {
      setDownloading(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: 12 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -12 }}
      className="space-y-4 pt-2 pb-10"
    >
      <div className="flex items-center justify-between">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-[11px] text-white/40 hover:text-white/70 transition"
        >
          ← All chapters
        </button>
        <button
          onClick={handleDownload}
          disabled={downloading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-white/50 hover:text-white/80 transition border border-white/10 disabled:opacity-40"
        >
          {downloading ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Download className="w-3 h-3" />
          )}
          Download .txt
        </button>
      </div>

      <div>
        <p className="text-[10px] font-medium uppercase tracking-wider text-white/30 mb-1">
          {formatPeriod(chapter.period_month)}
        </p>
        <h2 className="text-white text-base font-semibold leading-snug">{chapter.title}</h2>
      </div>

      <div
        className="rounded-2xl p-5"
        style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
      >
        <p className="text-white/60 text-xs leading-relaxed whitespace-pre-wrap">
          {chapter.content ?? "Loading…"}
        </p>
      </div>
    </motion.div>
  );
}

export function LegacyChapters({ currentPersona, isPower }: LegacyChaptersProps) {
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [selected, setSelected] = useState<Chapter | null>(null);
  const [error, setError] = useState<string | null>(null);

  const companionId = currentPersona?.id ?? "aria";
  const period = currentPeriod();
  const hasCurrentMonth = chapters.some((c) => c.period_month === period);

  const fetchList = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch(`${BASE}/api/legacy-chapters/list`);
      if (resp.ok) {
        const data = await resp.json();
        setChapters(data.chapters ?? []);
      }
    } catch {
      setError("Couldn't load chapters.");
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const resp = await apiFetch(
        `${BASE}/api/legacy-chapters/generate?companion_id=${companionId}`,
        { method: "POST" }
      );
      if (resp.ok) {
        const data = await resp.json();
        const ch: Chapter = data.chapter;
        setChapters((prev) =>
          data.already_existed ? prev : [{ id: ch.id, period_month: ch.period_month, title: ch.title, created_at: ch.created_at }, ...prev]
        );
        // Load full chapter detail
        const full = await apiFetch(`${BASE}/api/legacy-chapters/${ch.id}`);
        if (full.ok) {
          const fd = await full.json();
          setSelected(fd.chapter);
        } else {
          setSelected(ch);
        }
      } else if (resp.status === 403) {
        setError("Power plan required to generate Legacy Chapters.");
      } else {
        setError("Generation failed. Please try again.");
      }
    } catch {
      setError("Generation failed. Please try again.");
    } finally {
      setGenerating(false);
    }
  };

  const openChapter = async (stub: Chapter) => {
    if (stub.content) { setSelected(stub); return; }
    try {
      const resp = await apiFetch(`${BASE}/api/legacy-chapters/${stub.id}`);
      if (resp.ok) {
        const data = await resp.json();
        setSelected(data.chapter);
      }
    } catch {
      setSelected(stub);
    }
  };

  useEffect(() => {
    if (isPower) fetchList();
    else setLoading(false);
  }, [isPower]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!isPower) return <LockedTeaser />;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-5 h-5 text-amber-400 animate-spin" />
      </div>
    );
  }

  return (
    <AnimatePresence mode="wait">
      {selected ? (
        <ChapterDetail key="detail" chapter={selected} onBack={() => setSelected(null)} />
      ) : (
        <motion.div
          key="list"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          className="space-y-4 pt-2 pb-10"
        >
          {/* Header */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] font-medium uppercase tracking-wider text-white/30">Power feature</p>
              <p className="text-white/70 text-xs font-medium mt-0.5">One chapter per month</p>
            </div>
            <button
              onClick={fetchList}
              className="p-1.5 rounded-lg text-white/30 hover:text-white/60 transition border border-white/10"
              title="Refresh"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Generate CTA — only if no chapter exists for current month */}
          {!hasCurrentMonth && (
            <div
              className="rounded-2xl p-5 flex flex-col items-center text-center"
              style={{
                background: "rgba(217,119,6,0.07)",
                border: "1px solid rgba(217,119,6,0.20)",
              }}
            >
              <ScrollText className="w-6 h-6 mb-3" style={{ color: "rgba(251,191,36,0.65)" }} />
              <p className="text-white/70 text-xs font-medium mb-1">
                {formatPeriod(period)} chapter not yet written
              </p>
              <p className="text-white/35 text-[11px] mb-4 leading-relaxed max-w-[200px]">
                {currentPersona?.name ?? "Your companion"} will craft this month's chapter from
                your conversations and memories.
              </p>
              {error && <p className="text-red-400 text-xs mb-3">{error}</p>}
              <button
                onClick={handleGenerate}
                disabled={generating}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-white transition disabled:opacity-50"
                style={{
                  background: "linear-gradient(135deg, #d97706, #b45309)",
                  boxShadow: "0 4px 16px rgba(217,119,6,0.30)",
                }}
              >
                {generating ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Sparkles className="w-4 h-4" />
                )}
                {generating ? "Writing your chapter…" : "Write This Month's Chapter"}
              </button>
            </div>
          )}

          {hasCurrentMonth && error && (
            <p className="text-red-400 text-xs text-center">{error}</p>
          )}

          {/* Chapter list */}
          {chapters.length === 0 && !generating && (
            <p className="text-white/25 text-xs text-center py-8">
              No chapters yet — generate your first one above.
            </p>
          )}

          {chapters.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-white/25 px-1">
                Your story so far
              </p>
              {chapters.map((ch) => (
                <motion.button
                  key={ch.id}
                  onClick={() => openChapter(ch)}
                  className="w-full text-left rounded-2xl px-4 py-3.5 flex items-center justify-between gap-3 transition"
                  style={{
                    background: ch.period_month === period
                      ? "rgba(217,119,6,0.08)"
                      : "rgba(255,255,255,0.03)",
                    border: `1px solid ${ch.period_month === period ? "rgba(217,119,6,0.20)" : "rgba(255,255,255,0.07)"}`,
                  }}
                  whileHover={{ scale: 1.005 }}
                  whileTap={{ scale: 0.995 }}
                >
                  <div className="min-w-0">
                    <p className="text-[10px] font-medium uppercase tracking-wider text-white/30 mb-0.5">
                      {formatPeriod(ch.period_month)}
                    </p>
                    <p className="text-white/75 text-xs font-medium truncate">{ch.title}</p>
                  </div>
                  <ChevronRight className="w-3.5 h-3.5 text-white/25 shrink-0" />
                </motion.button>
              ))}
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
