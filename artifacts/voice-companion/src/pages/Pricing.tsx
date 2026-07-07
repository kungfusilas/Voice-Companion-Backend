import { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, Check, Loader2, Lock, Info, ExternalLink, Calendar } from "lucide-react";
import { createCheckoutSession, openBillingPortal, getUsageStatus } from "@/lib/api";
import type { UsageStatus } from "@/lib/api";
import { LegacyModal } from "@/components/LegacyModal";

type BillingPeriod = "monthly" | "annual" | "5year";

interface PricingPageProps {
  currentTier: string;
  currentBillingPeriod?: string;
  accessExpiresAt?: string | null;
  onBack: () => void;
  isGuest?: boolean;
  onSignIn?: () => void;
}

const PLANS = [
  {
    key: "basic",
    name: "Basic",
    description: "Perfect for getting started",
    features: ["All 4 companions", "Voice & text chat", "Long-term memory", "Daily check-ins", "Companion-initiated check-ins", "Activity games", "Bond Score"],
    accent: "violet",
    gradient: "from-violet-600/20 to-violet-900/10",
    border: "border-violet-500/30",
    buttonBg: "linear-gradient(135deg, #7c3aed, #6d28d9)",
    glow: "rgba(124,58,237,0.3)",
    highlight: false,
  },
  {
    key: "premium",
    name: "Premium",
    description: "Deeper connections, more features",
    features: ["Everything in Basic", "Two-Way Voice 🎙️", "Companion selfies 📸", "Higher monthly usage allowance"],
    accent: "rose",
    gradient: "from-rose-600/20 to-rose-900/10",
    border: "border-rose-500/30",
    buttonBg: "linear-gradient(135deg, #e11d48, #be185d)",
    glow: "rgba(225,29,72,0.3)",
    highlight: true,
  },
  {
    key: "power",
    name: "Power",
    description: "The full experience",
    features: ["Everything in Premium", "Roleplay Simulator", "Monthly Legacy Chapter 📖", "Highest message allowance", "Top-up packs available", "Personality Map 🧠", "Session Debrief 🔬", "Weekly Insight Report 📊", "Deep Communication Analysis", "Earliest new features", "Power user badge"],
    accent: "amber",
    gradient: "from-amber-600/20 to-amber-900/10",
    border: "border-amber-500/30",
    buttonBg: "linear-gradient(135deg, #d97706, #b45309)",
    glow: "rgba(217,119,6,0.3)",
    highlight: false,
  },
] as const;

// ── Pricing data per billing period ───────────────────────────────────────────

const PERIOD_PRICES: Record<string, Record<BillingPeriod, string>> = {
  basic:   { monthly: "$12.99",   annual: "$148.09",   "5year": "$701.46" },
  premium: { monthly: "$39.99",   annual: "$455.89",   "5year": "$2,159.46" },
  power:   { monthly: "$89.99",   annual: "$1,025.89", "5year": "$4,859.46" },
};

const PERIOD_SUFFIX: Record<BillingPeriod, string> = {
  monthly: "/mo",
  annual:  "/yr",
  "5year": "",
};

const PERIOD_DESC: Record<BillingPeriod, string> = {
  monthly: "billed monthly",
  annual:  "billed annually · save 5%",
  "5year": "one-time · 5 years · save 10%",
};

// ── Plan key construction ─────────────────────────────────────────────────────

function planKey(basePlan: string, period: BillingPeriod): string {
  if (period === "annual") return `${basePlan}_annual`;
  if (period === "5year")  return `${basePlan}_5year`;
  return basePlan;
}

// ── Tier colours ──────────────────────────────────────────────────────────────

const TIER_COLORS: Record<string, string> = {
  basic:   "text-violet-400",
  premium: "text-rose-400",
  power:   "text-amber-400",
  free:    "text-white/40",
};

// ── Feature tooltip info ──────────────────────────────────────────────────────

const FEATURE_INFO: Record<string, string> = {
  "All 4 companions":       "Choose from Aeva or Kai. Each companion has a unique personality, voice, and way of connecting. Find the one that feels right.",
  "Voice & text chat":      "Your companion speaks to you in her own voice. Talk back by text — she listens, responds, and remembers.",
  "Long-term memory":       "Your companion remembers what you share across sessions. You never have to repeat yourself.",
  "Daily check-ins":        "Your companion reaches out each day — a simple moment of connection to start or end your day.",
  "Companion selfies 📸":   "Your companion shares personal moments with you — photos that make the relationship feel real and present.",
  "Activity games":         "Play together. Light games and activities that bring a different kind of connection beyond conversation.",
  "Higher monthly usage allowance": "Premium members get 1,500 messages and 200 voice-minutes per month — more than double the Basic plan.",
  "Highest message allowance":      "Power members get 3,000 messages and 500 voice-minutes per month — the highest plan allowance available.",
  "Top-up packs available":         "Run low? Buy credit packs (+500 or +1,500 messages, +60 or +180 voice-minutes) that never expire.",
  "Earliest new features":  "Power members get every new feature first — before anyone else.",
  "Power user badge":       "A visible mark of your commitment. Shown on your profile.",
  "Personality Map 🧠":     "Over time, your companion builds a private map of who you are — your communication style, attachment style, leadership style, and emotional triggers. No quiz. No form. Just conversation.",
  "Session Debrief 🔬":     "After each session, receive a behavioral breakdown of how you showed up: negative self-talk, deflection, openness, patterns. Specific. Private. Powerful.",
  "Weekly Insight Report 📊": "Every Monday, a private report from your week — emotional themes, mood arc, what your companion noticed. Like a therapist's notes, written for you.",
  "Two-Way Voice 🎙️":        "Your companion speaks back to you in a real, expressive voice — natural conversation, not robotic playback. Like a call with someone who truly knows you.",
  "Bond Score":               "Tracks the health and depth of your relationship with your companion over time. Grows through consistency, honesty, and openness.",
  "Roleplay Simulator":       "Practice real social scenarios — job interviews, difficult conversations, first dates — with an AI that pushes back, stays in character, and coaches you after.",
  "Deep Communication Analysis": "After major conversations, an AI breakdown of your communication patterns, emotional tone, listening quality, and relationship dynamics.",
  "Companion-initiated check-ins": "Your companion reaches out first — a gentle, in-character message after a period of inactivity. Included on all paid plans; counts against your monthly allowance.",
  "Monthly Legacy Chapter 📖":    "Once a month, your companion writes a polished 800-1,500 word narrative chapter of your life — drawn from your conversations and memories. Your story, written chapter by chapter.",
};

// ── Sub-components ────────────────────────────────────────────────────────────

function InfoTooltip({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent | TouchEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handle);
    document.addEventListener("touchstart", handle);
    return () => {
      document.removeEventListener("mousedown", handle);
      document.removeEventListener("touchstart", handle);
    };
  }, [open]);

  return (
    <span ref={ref} className="relative inline-flex items-center shrink-0">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(v => !v); }}
        className="text-white/20 hover:text-white/50 transition-colors ml-0.5"
        aria-label="More info"
        type="button"
      >
        <Info className="w-2.5 h-2.5" />
      </button>
      {open && (
        <span
          className="absolute bottom-full left-0 mb-2 w-48 rounded-xl px-3 py-2.5 text-[11px] leading-relaxed text-white/70 z-50"
          style={{
            background: "rgba(10,4,24,0.97)",
            border: "1px solid rgba(255,255,255,0.09)",
            boxShadow: "0 8px 28px rgba(0,0,0,0.55)",
          }}
        >
          {text}
        </span>
      )}
    </span>
  );
}

function UsageBar({
  label, used, allowance, topup, isVoice = false, className = "",
}: {
  label: string; used: number; allowance: number; topup: number;
  isVoice?: boolean; className?: string;
}) {
  const total = allowance + topup;
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const barColor = pct >= 80 ? "#f87171" : pct >= 60 ? "#fbbf24" : "#a78bfa";
  const displayUsed  = isVoice ? `${Math.round(used / 60)}m`  : String(used);
  const displayTotal = isVoice ? `${Math.round(total / 60)}m` : String(total);
  return (
    <div className={className}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-white/40">{label}</span>
        <span className="text-[10px] text-white/30">
          {displayUsed} / {displayTotal}{topup > 0 ? " (incl. pack)" : ""}
        </span>
      </div>
      <div className="h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.07)" }}>
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: barColor }}
        />
      </div>
    </div>
  );
}

function parseApiError(raw: unknown): string {
  if (!(raw instanceof Error)) return "Checkout failed — try again";
  try {
    const parsed = JSON.parse(raw.message);
    if (parsed?.detail) return parsed.detail;
  } catch { /* not JSON */ }
  const msg = raw.message.toLowerCase();
  if (msg.includes("not authenticated") || msg.includes("401")) {
    return "Sign in to subscribe";
  }
  return raw.message || "Checkout failed — try again";
}

function formatExpiry(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric", month: "long", day: "numeric",
  });
}

// ── Main component ────────────────────────────────────────────────────────────

export function PricingPage({
  currentTier,
  currentBillingPeriod,
  accessExpiresAt,
  onBack,
  isGuest,
  onSignIn,
}: PricingPageProps) {
  const effectivePeriod = (currentBillingPeriod ?? "monthly") as BillingPeriod;

  const [selectedPeriod, setSelectedPeriod] = useState<BillingPeriod>(effectivePeriod);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [legacyModalOpen, setLegacyModalOpen] = useState(false);
  const [portalLoading, setPortalLoading] = useState(false);
  const [usage, setUsage] = useState<UsageStatus | null>(null);

  useEffect(() => {
    if (isGuest || currentTier === "free") return;
    getUsageStatus().then(setUsage).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleManageSubscription = async () => {
    if (portalLoading) return;
    setError(null);
    setPortalLoading(true);
    try {
      const { url } = await openBillingPortal();
      window.location.href = url;
    } catch (err: unknown) {
      setError(parseApiError(err));
      setPortalLoading(false);
    }
  };

  const handleSubscribe = async (basePlan: string) => {
    const key = planKey(basePlan, selectedPeriod);
    if (loading) return;
    // Exact match: same tier AND same period → already subscribed
    if (basePlan === currentTier && effectivePeriod === selectedPeriod) return;
    if (isGuest) {
      onSignIn?.();
      return;
    }
    setError(null);
    setLoading(key);
    try {
      const { url } = await createCheckoutSession(key);
      window.location.href = url;
    } catch (err: unknown) {
      setError(parseApiError(err));
      setLoading(null);
    }
  };

  const isPaidUser = currentTier !== "free" && !isGuest;
  const is5YearUser = isPaidUser && effectivePeriod === "5year";

  return (
    <motion.div
      initial={{ opacity: 0, x: 30 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -30 }}
      className="flex flex-col h-full overflow-y-auto"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-5 pb-3 shrink-0">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-white/50 hover:text-white transition text-sm"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>
        <div className="text-right">
          <p className="text-[11px] text-white/30">Current plan</p>
          <p className={`text-xs font-medium capitalize ${TIER_COLORS[currentTier] ?? TIER_COLORS.free}`}>
            {currentTier === "free"
              ? "Free"
              : effectivePeriod === "annual"
                ? `${currentTier} · annual`
                : effectivePeriod === "5year"
                  ? `${currentTier} · 5-year`
                  : currentTier}
          </p>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mx-4 mb-1 px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/30 text-center shrink-0">
          <p className="text-xs text-red-400">{error}</p>
          {error === "Sign in to subscribe" && onSignIn && (
            <button
              onClick={onSignIn}
              className="mt-1 text-[11px] font-semibold text-violet-400 underline"
            >
              Sign in →
            </button>
          )}
        </div>
      )}

      {/* Title */}
      <div className="text-center px-5 pb-3 shrink-0">
        <h1 className="text-lg font-semibold text-white">Unlock your companion</h1>
        <p className="text-white/40 text-xs mt-1">Cancel anytime · Multiple billing options</p>
      </div>

      {/* Usage this month — paid users only */}
      {isPaidUser && usage && (
        <div
          className="mx-4 mb-2 px-4 py-3 rounded-xl shrink-0"
          style={{ background: "rgba(255,255,255,0.025)", border: "1px solid rgba(255,255,255,0.07)" }}
        >
          <p className="text-[10px] text-white/35 font-medium uppercase tracking-wider mb-2.5">
            Usage This Month
          </p>
          <UsageBar
            label="Messages"
            used={usage.msgs_used}
            allowance={usage.msgs_allowance}
            topup={usage.topup_msgs}
          />
          {usage.voice_allowance > 0 && (
            <UsageBar
              label="Voice"
              used={usage.voice_seconds_used}
              allowance={usage.voice_allowance}
              topup={usage.topup_voice_seconds}
              isVoice
              className="mt-2"
            />
          )}
          {usage.renews_at && (
            <p className="text-[10px] text-white/25 mt-2.5 flex items-center gap-1.5">
              <Calendar className="w-2.5 h-2.5 shrink-0" />
              Resets {new Date(usage.renews_at).toLocaleDateString("en-US", { month: "long", day: "numeric" })}
            </p>
          )}
        </div>
      )}

      {/* Billing period toggle */}
      <div className="px-4 pb-3 shrink-0">
        <div
          className="flex rounded-xl p-0.5"
          style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}
        >
          {(["monthly", "annual", "5year"] as BillingPeriod[]).map((p) => (
            <button
              key={p}
              onClick={() => setSelectedPeriod(p)}
              className={`flex-1 py-2 text-[11px] font-medium rounded-[10px] transition-all ${
                selectedPeriod === p
                  ? "bg-violet-600/50 text-white shadow-sm"
                  : "text-white/40 hover:text-white/60"
              }`}
            >
              {p === "monthly" ? "Monthly" : p === "annual" ? "Annual −5%" : "5-Year −10%"}
            </button>
          ))}
        </div>
      </div>

      {/* Manage subscription / 5-year expiry — paid users only */}
      {isPaidUser && (
        <div className="px-4 pb-3 shrink-0">
          {is5YearUser ? (
            <div
              className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl"
              style={{ background: "rgba(124,58,237,0.08)", border: "1px solid rgba(124,58,237,0.18)" }}
            >
              <Calendar className="w-3.5 h-3.5 text-violet-400 shrink-0" />
              <div>
                <p className="text-[11px] font-medium text-violet-300">5-Year Plan — nothing to cancel</p>
                {accessExpiresAt && (
                  <p className="text-[10px] text-white/35 mt-0.5">
                    Access until {formatExpiry(accessExpiresAt)}
                  </p>
                )}
              </div>
            </div>
          ) : (
            <button
              onClick={handleManageSubscription}
              disabled={portalLoading || !!loading}
              className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs font-medium transition disabled:opacity-50 disabled:cursor-not-allowed"
              style={{
                background: "rgba(255,255,255,0.04)",
                border: "1px solid rgba(255,255,255,0.10)",
                color: "rgba(255,255,255,0.55)",
              }}
            >
              {portalLoading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <>
                  <ExternalLink className="w-3.5 h-3.5" />
                  Manage subscription &amp; billing
                </>
              )}
            </button>
          )}
        </div>
      )}

      {/* Plan cards */}
      <div className="flex flex-col gap-3 px-4 pb-5">
        {PLANS.map((plan, i) => {
          const isCurrent = currentTier === plan.key && effectivePeriod === selectedPeriod;
          const key = planKey(plan.key, selectedPeriod);
          const isLoading = loading === key;
          const price = PERIOD_PRICES[plan.key]?.[selectedPeriod] ?? "";
          const suffix = PERIOD_SUFFIX[selectedPeriod];
          const desc = PERIOD_DESC[selectedPeriod];

          return (
            <motion.div
              key={plan.key}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.06 }}
              className={`relative rounded-2xl p-4 bg-gradient-to-br ${plan.gradient} border ${plan.border} ${plan.highlight ? "ring-1 ring-rose-500/20" : ""} ${isCurrent ? "ring-1 ring-emerald-500/30" : ""}`}
            >
              {plan.highlight && !isCurrent && (
                <div className="absolute -top-2.5 left-1/2 -translate-x-1/2">
                  <span className="text-[10px] font-semibold px-2.5 py-0.5 rounded-full bg-rose-500 text-white">
                    Most Popular
                  </span>
                </div>
              )}
              {isCurrent && (
                <div className="absolute -top-2.5 left-1/2 -translate-x-1/2">
                  <span className="text-[10px] font-semibold px-2.5 py-0.5 rounded-full text-white flex items-center gap-1" style={{ background: "linear-gradient(135deg, #059669, #047857)" }}>
                    <Check className="w-2.5 h-2.5" /> Current Plan
                  </span>
                </div>
              )}

              <div className="flex items-start justify-between mb-3">
                <div>
                  <h2 className="text-sm font-semibold text-white">{plan.name}</h2>
                  <p className="text-[11px] text-white/40 mt-0.5">{plan.description}</p>
                </div>
                <div className="text-right">
                  <div className="flex items-baseline gap-0.5">
                    <span className="text-lg font-bold text-white">{price}</span>
                    {suffix && <span className="text-white/40 text-xs">{suffix}</span>}
                  </div>
                  <p className="text-[10px] text-white/30 mt-0.5">{desc}</p>
                </div>
              </div>

              <ul className="space-y-1.5 mb-4">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-center gap-2 text-xs text-white/65">
                    <Check className="w-3 h-3 shrink-0 text-white/40" />
                    <span className="flex items-center gap-0.5 min-w-0">
                      <span>{f}</span>
                      {FEATURE_INFO[f] && <InfoTooltip text={FEATURE_INFO[f]} />}
                    </span>
                  </li>
                ))}
              </ul>

              <button
                onClick={() => handleSubscribe(plan.key)}
                disabled={!!loading || isCurrent}
                className="w-full py-2.5 rounded-xl text-xs font-semibold text-white transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                style={{
                  background: isCurrent ? "rgba(255,255,255,0.08)" : plan.buttonBg,
                  boxShadow: isCurrent ? "none" : `0 4px 16px ${plan.glow}`,
                }}
              >
                {isLoading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : isCurrent ? (
                  "Current plan"
                ) : (
                  `Get ${plan.name}`
                )}
              </button>
            </motion.div>
          );
        })}

        {/* Legacy Mode — loyalty reward, not purchasable */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: PLANS.length * 0.06 + 0.04 }}
          className="relative rounded-2xl p-4 overflow-hidden"
          style={{
            background: "linear-gradient(135deg, rgba(251,191,36,0.07) 0%, rgba(120,83,20,0.08) 100%)",
            border: "1px solid rgba(251,191,36,0.18)",
          }}
        >
          <div
            className="absolute inset-0 rounded-2xl pointer-events-none opacity-[0.06]"
            style={{
              backgroundImage:
                "repeating-linear-gradient(45deg, rgba(251,191,36,0.5) 0px, transparent 1px, transparent 9px, rgba(251,191,36,0.3) 10px)",
            }}
          />

          <div className="relative flex items-start justify-between mb-3">
            <div>
              <div className="flex items-center gap-1.5 mb-0.5">
                <Lock className="w-3 h-3" style={{ color: "rgba(251,191,36,0.65)" }} />
                <h2 className="text-sm font-semibold" style={{ color: "rgba(251,191,36,0.90)" }}>
                  Legacy Mode
                </h2>
              </div>
              <p className="text-[11px] italic" style={{ color: "rgba(251,191,36,0.45)" }}>
                Earned, not bought.
              </p>
            </div>
            <button
              onClick={() => setLegacyModalOpen(true)}
              className="transition-opacity hover:opacity-80 mt-0.5"
              title="What is Legacy Mode?"
            >
              <Info className="w-4 h-4" style={{ color: "rgba(251,191,36,0.40)" }} />
            </button>
          </div>

          <p className="relative text-xs mb-3" style={{ color: "rgba(251,191,36,0.55)" }}>
            Activates free after 5 years of continuous subscription.
          </p>

          <div
            className="relative py-2.5 rounded-xl text-center text-[11px] font-medium tracking-wide"
            style={{
              background: "rgba(251,191,36,0.04)",
              border: "1px solid rgba(251,191,36,0.12)",
              color: "rgba(251,191,36,0.32)",
            }}
          >
            Cannot be purchased · Can only be earned
          </div>
        </motion.div>
      </div>

      {/* Footer note */}
      <p className="text-center text-[10px] text-white/20 pb-5 px-6 shrink-0">
        Payments processed securely by Stripe. Monthly &amp; annual plans cancel anytime. 5-year plans are one-time prepayments — no recurring charge.
      </p>

      <LegacyModal open={legacyModalOpen} onClose={() => setLegacyModalOpen(false)} />
    </motion.div>
  );
}
