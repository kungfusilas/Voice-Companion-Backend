import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { Loader2, Brain, Heart, Zap, Flame, RefreshCw } from "lucide-react";
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

interface DimensionData {
  label?: string | null;
  signals?: string[];
  positive?: string[];
  negative?: string[];
}

interface PersonalityMapData {
  communication_style?: DimensionData;
  attachment_style?: DimensionData;
  leadership_style?: DimensionData;
  emotional_triggers?: DimensionData;
  conversation_count?: number;
  last_updated?: string | null;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "Not yet analyzed";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "long", day: "numeric", year: "numeric",
  });
}

function DimensionCard({
  icon: Icon,
  title,
  color,
  borderColor,
  bgColor,
  label,
  signals,
  delay,
}: {
  icon: React.ElementType;
  title: string;
  color: string;
  borderColor: string;
  bgColor: string;
  label?: string | null;
  signals?: string[];
  delay: number;
}) {
  const hasData = label || (signals && signals.length > 0);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      className="rounded-2xl p-4"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
    >
      <div className="flex items-center gap-2 mb-3">
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: bgColor, border: `1px solid ${borderColor}` }}
        >
          <Icon className="w-3.5 h-3.5" style={{ color }} />
        </div>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">{title}</p>
      </div>

      {!hasData ? (
        <p className="text-white/25 text-xs italic">Building profile through conversation…</p>
      ) : (
        <div>
          {label && (
            <p className="text-sm font-medium text-white/80 mb-2">{label}</p>
          )}
          {signals && signals.length > 0 && (
            <ul className="space-y-1">
              {signals.map((s, i) => (
                <li key={i} className="flex items-start gap-2 text-xs text-white/45">
                  <span className="mt-1.5 w-1 h-1 rounded-full shrink-0" style={{ background: color }} />
                  {s}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </motion.div>
  );
}

function TriggersCard({ data, delay }: { data?: DimensionData; delay: number }) {
  const pos = data?.positive ?? [];
  const neg = data?.negative ?? [];
  const hasData = pos.length > 0 || neg.length > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      className="rounded-2xl p-4"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
    >
      <div className="flex items-center gap-2 mb-3">
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: "rgba(251,191,36,0.10)", border: "1px solid rgba(251,191,36,0.20)" }}
        >
          <Flame className="w-3.5 h-3.5" style={{ color: "rgba(251,191,36,0.8)" }} />
        </div>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">Emotional Triggers</p>
      </div>

      {!hasData ? (
        <p className="text-white/25 text-xs italic">Building profile through conversation…</p>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-[10px] font-medium uppercase tracking-wider mb-1.5" style={{ color: "rgba(52,211,153,0.7)" }}>
              Energizes
            </p>
            {pos.length === 0
              ? <p className="text-white/25 text-xs italic">—</p>
              : pos.map((t, i) => (
                  <p key={i} className="text-xs text-white/55 mb-1">{t}</p>
                ))
            }
          </div>
          <div>
            <p className="text-[10px] font-medium uppercase tracking-wider mb-1.5" style={{ color: "rgba(251,113,133,0.7)" }}>
              Drains
            </p>
            {neg.length === 0
              ? <p className="text-white/25 text-xs italic">—</p>
              : neg.map((t, i) => (
                  <p key={i} className="text-xs text-white/55 mb-1">{t}</p>
                ))
            }
          </div>
        </div>
      )}
    </motion.div>
  );
}

export function PersonalityMap() {
  const [pmap, setPmap] = useState<PersonalityMapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMap = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch(`${BASE}/api/personality`);
      if (resp.ok) {
        const data = await resp.json();
        setPmap(data.personality_map ?? null);
      } else if (resp.status === 403) {
        setError("Power tier required to access Personality Mapping.");
      } else {
        setError("Couldn't load your personality map.");
      }
    } catch {
      setError("Couldn't load your personality map.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchMap(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
        <Brain className="w-8 h-8 text-white/20 mb-3" />
        <p className="text-white/40 text-sm">{error}</p>
      </div>
    );
  }

  const count = pmap?.conversation_count ?? 0;

  return (
    <div className="space-y-4 pt-2 pb-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wider text-white/30">Built from conversation</p>
          <p className="text-white/70 text-xs font-medium mt-0.5">
            {count === 0 ? "No data yet" : `${count} exchange${count !== 1 ? "s" : ""} analyzed`}
          </p>
        </div>
        <button
          onClick={fetchMap}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-white/50 hover:text-white/80 transition border border-white/10"
          title="Refresh"
        >
          <RefreshCw className="w-3 h-3" />
          Refresh
        </button>
      </div>

      {count === 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="rounded-2xl px-4 py-5 text-center"
          style={{ background: "rgba(139,92,246,0.06)", border: "1px solid rgba(139,92,246,0.15)" }}
        >
          <Brain className="w-8 h-8 text-violet-400/50 mx-auto mb-3" />
          <p className="text-white/55 text-xs leading-relaxed">
            Your personality map builds organically as you have conversations.
            No quiz, no form — just talk. After a few exchanges, patterns will start to emerge here.
          </p>
        </motion.div>
      )}

      <DimensionCard
        icon={Brain}
        title="Communication Style"
        color="rgba(139,92,246,0.85)"
        borderColor="rgba(139,92,246,0.25)"
        bgColor="rgba(139,92,246,0.10)"
        label={pmap?.communication_style?.label}
        signals={pmap?.communication_style?.signals}
        delay={0.05}
      />

      <DimensionCard
        icon={Heart}
        title="Attachment Style"
        color="rgba(244,114,182,0.85)"
        borderColor="rgba(244,114,182,0.25)"
        bgColor="rgba(244,114,182,0.10)"
        label={pmap?.attachment_style?.label}
        signals={pmap?.attachment_style?.signals}
        delay={0.10}
      />

      <DimensionCard
        icon={Zap}
        title="Leadership Style"
        color="rgba(34,211,238,0.85)"
        borderColor="rgba(34,211,238,0.20)"
        bgColor="rgba(34,211,238,0.08)"
        label={pmap?.leadership_style?.label}
        signals={pmap?.leadership_style?.signals}
        delay={0.15}
      />

      <TriggersCard data={pmap?.emotional_triggers} delay={0.20} />

      {pmap?.last_updated && (
        <p className="text-center text-[10px] text-white/20">
          Last updated {formatDate(pmap.last_updated)}
        </p>
      )}
    </div>
  );
}
