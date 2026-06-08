import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { TrendingUp, TrendingDown, Minus, Activity } from "lucide-react";
import { apiFetchJSON } from "@/lib/api";

const SKILLS: { key: string; label: string }[] = [
  { key: "listening",            label: "Listening"            },
  { key: "empathy",              label: "Empathy"              },
  { key: "curiosity",            label: "Curiosity"            },
  { key: "emotional_regulation", label: "Emotional Regulation" },
  { key: "conflict_resolution",  label: "Conflict Resolution"  },
  { key: "follow_through",       label: "Follow-through"       },
  { key: "humor",                label: "Humor"                },
  { key: "confidence",           label: "Confidence"           },
];

interface ScoreRow {
  bond_score: number;
  created_at: string;
  [key: string]: number | string;
}

interface BondScoreData {
  latest: ScoreRow | null;
  previous: ScoreRow | null;
  history: { bond_score: number; created_at: string }[];
  trend: number | null;
  monthly_trend: number | null;
}

// ── Sparkline ─────────────────────────────────────────────────────────────────

function Sparkline({ data }: { data: number[] }) {
  if (data.length < 2) return null;
  const W = 280;
  const H = 52;
  const min = Math.max(0, Math.min(...data) - 5);
  const max = Math.min(100, Math.max(...data) + 5);
  const range = max - min || 1;

  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * W;
    const y = H - ((v - min) / range) * (H - 4) - 2;
    return [x, y] as [number, number];
  });

  // Build smooth path using cubic bezier approximation
  let d = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1];
    const [x1, y1] = pts[i];
    const cx = (x0 + x1) / 2;
    d += ` C ${cx} ${y0}, ${cx} ${y1}, ${x1} ${y1}`;
  }

  // Fill path (area under curve)
  const fillD = `${d} L ${pts[pts.length - 1][0]} ${H} L ${pts[0][0]} ${H} Z`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: H }}>
      <defs>
        <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(139,92,246,0.35)" />
          <stop offset="100%" stopColor="rgba(139,92,246,0)" />
        </linearGradient>
        <linearGradient id="sparkLine" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="rgba(139,92,246,0.4)" />
          <stop offset="100%" stopColor="rgba(168,85,247,0.9)" />
        </linearGradient>
      </defs>
      <path d={fillD} fill="url(#sparkFill)" />
      <path d={d} fill="none" stroke="url(#sparkLine)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {/* Latest dot */}
      <circle
        cx={pts[pts.length - 1][0]}
        cy={pts[pts.length - 1][1]}
        r="3.5"
        fill="rgba(168,85,247,1)"
      />
    </svg>
  );
}

// ── Score ring ────────────────────────────────────────────────────────────────

function ScoreRing({ score }: { score: number }) {
  const R = 58;
  const circ = 2 * Math.PI * R;
  const dash = (score / 100) * circ;

  return (
    <div className="relative flex items-center justify-center" style={{ width: 148, height: 148 }}>
      <svg width="148" height="148" viewBox="0 0 148 148" className="absolute inset-0 -rotate-90">
        {/* Track */}
        <circle cx="74" cy="74" r={R} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="10" />
        {/* Progress */}
        <circle
          cx="74"
          cy="74"
          r={R}
          fill="none"
          stroke="url(#ringGrad)"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circ}`}
        />
        <defs>
          <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#7c3aed" />
            <stop offset="100%" stopColor="#db2777" />
          </linearGradient>
        </defs>
      </svg>
      <div className="flex flex-col items-center z-10">
        <motion.span
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          className="text-4xl font-bold text-white leading-none tracking-tight"
        >
          {score}
        </motion.span>
        <span className="text-white/35 text-[10px] mt-1 font-medium tracking-wider uppercase">Bond Score</span>
      </div>
    </div>
  );
}

// ── Skill bar ─────────────────────────────────────────────────────────────────

function SkillBar({ label, score, delta }: { label: string; score: number; delta: number | null }) {
  const pct = score;
  const deltaStr = delta === null ? null : delta > 0 ? `+${delta}` : delta < 0 ? `${delta}` : null;
  const deltaColor = delta === null || delta === 0 ? "text-white/30" : delta > 0 ? "text-emerald-400/80" : "text-red-400/70";

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-white/65 text-xs">{label}</span>
        <div className="flex items-center gap-2">
          {deltaStr && (
            <span className={`text-[10px] font-medium ${deltaColor}`}>{deltaStr}</span>
          )}
          <span className="text-white/80 text-xs font-semibold tabular-nums w-6 text-right">{score}</span>
        </div>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.07)" }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className="h-full rounded-full"
          style={{
            background:
              pct >= 75 ? "linear-gradient(90deg, #7c3aed, #a855f7)" :
              pct >= 50 ? "linear-gradient(90deg, #6d28d9, #8b5cf6)" :
              "linear-gradient(90deg, #4c1d95, #6d28d9)",
          }}
        />
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function BondScore() {
  const [data, setData] = useState<BondScoreData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetchJSON<BondScoreData>("/companion/api/bond-score")
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // ── Empty state ──────────────────────────────────────────────────────────────
  if (!data?.latest) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center px-4">
        <div
          className="w-24 h-24 rounded-full flex items-center justify-center mb-5"
          style={{ background: "rgba(139,92,246,0.08)", border: "1px solid rgba(139,92,246,0.15)" }}
        >
          <Activity className="w-9 h-9 text-violet-400/50" />
        </div>
        <p className="text-white/60 text-sm font-medium mb-2">No Bond Score yet</p>
        <p className="text-white/30 text-xs leading-relaxed max-w-[200px]">
          Chat for a few exchanges and your relationship skills will be scored automatically.
        </p>
      </div>
    );
  }

  const { latest, previous, history, monthly_trend } = data;
  const scoreValues = history.map((h) => h.bond_score);

  // Monthly trend display
  const trendValue = monthly_trend;
  const TrendIcon = trendValue === null || trendValue === 0 ? Minus : trendValue > 0 ? TrendingUp : TrendingDown;
  const trendColor = trendValue === null || trendValue === 0 ? "text-white/30" : trendValue > 0 ? "text-emerald-400" : "text-red-400";
  const trendLabel =
    trendValue === null ? "No change data" :
    trendValue === 0 ? "Holding steady" :
    trendValue > 0 ? `↑ ${trendValue} pts this month` :
    `↓ ${Math.abs(trendValue)} pts this month`;

  return (
    <div className="space-y-5 pt-2">
      {/* Score ring + trend */}
      <div className="flex flex-col items-center py-4">
        <ScoreRing score={latest.bond_score} />
        <div className={`flex items-center gap-1.5 mt-3 text-xs font-medium ${trendColor}`}>
          <TrendIcon className="w-3.5 h-3.5" />
          <span>{trendLabel}</span>
        </div>
      </div>

      {/* Sparkline */}
      {scoreValues.length >= 2 && (
        <div
          className="rounded-2xl px-4 pt-3 pb-2"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
        >
          <p className="text-white/30 text-[10px] uppercase tracking-wider mb-2 font-medium">Score history</p>
          <Sparkline data={scoreValues} />
          <div className="flex justify-between mt-1">
            <span className="text-white/20 text-[9px]">Oldest</span>
            <span className="text-white/20 text-[9px]">Latest</span>
          </div>
        </div>
      )}

      {/* 8 skill bars */}
      <div
        className="rounded-2xl px-4 py-4 space-y-3.5"
        style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
      >
        <p className="text-white/30 text-[10px] uppercase tracking-wider font-medium mb-4">Relationship Skills</p>
        {SKILLS.map(({ key, label }) => {
          const score = Number(latest[key] ?? 50);
          const prevScore = previous ? Number(previous[key] ?? 50) : null;
          const delta = prevScore !== null ? score - prevScore : null;
          return <SkillBar key={key} label={label} score={score} delta={delta} />;
        })}
      </div>

      <p className="text-white/20 text-[10px] text-center pb-2 leading-relaxed">
        Scored automatically after each conversation
      </p>
    </div>
  );
}
