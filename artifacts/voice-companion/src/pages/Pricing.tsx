import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, Check, Loader2, Lock, Info } from "lucide-react";
import { createCheckoutSession } from "@/lib/api";
import { LegacyModal } from "@/components/LegacyModal";

interface PricingPageProps {
  currentTier: string;
  onBack: () => void;
}

const PLANS = [
  {
    key: "basic",
    name: "Basic",
    price: "$12.99",
    period: "/mo",
    description: "Perfect for getting started",
    features: ["All 4 companions", "Voice & text chat", "Long-term memory", "Daily check-ins"],
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
    price: "$39.99",
    period: "/mo",
    description: "Deeper connections, more features",
    features: ["Everything in Basic", "Two-Way Voice 🎙️", "Weekly Insight Report 📊", "Companion selfies 📸", "Activity games", "Priority responses"],
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
    price: "$89.99",
    period: "/mo",
    description: "The full experience, unlimited",
    features: ["Everything in Premium", "Unlimited messages", "Advanced memory", "Personality Map 🧠", "Session Debrief 🔬", "Earliest new features", "Power user badge"],
    accent: "amber",
    gradient: "from-amber-600/20 to-amber-900/10",
    border: "border-amber-500/30",
    buttonBg: "linear-gradient(135deg, #d97706, #b45309)",
    glow: "rgba(217,119,6,0.3)",
    highlight: false,
  },
] as const;

const TIER_COLORS: Record<string, string> = {
  basic:   "text-violet-400",
  premium: "text-rose-400",
  power:   "text-amber-400",
  free:    "text-white/40",
};

export function PricingPage({ currentTier, onBack }: PricingPageProps) {
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [legacyModalOpen, setLegacyModalOpen] = useState(false);

  const handleSubscribe = async (planKey: string) => {
    if (loading || planKey === currentTier) return;
    setError(null);
    setLoading(planKey);
    try {
      const { url } = await createCheckoutSession(planKey);
      window.location.href = url;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Checkout failed — try again");
      setLoading(null);
    }
  };

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
            {currentTier === "free" ? "Free" : currentTier}
          </p>
        </div>
      </div>

      {/* Title */}
      <div className="text-center px-5 pb-4 shrink-0">
        <h1 className="text-lg font-semibold text-white">Unlock your companion</h1>
        <p className="text-white/40 text-xs mt-1">Cancel anytime · Billed monthly</p>
      </div>

      {/* Plan cards */}
      <div className="flex flex-col gap-3 px-4 pb-5">
        {PLANS.map((plan, i) => {
          const isCurrent = currentTier === plan.key;
          const isLoading = loading === plan.key;

          return (
            <motion.div
              key={plan.key}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.06 }}
              className={`relative rounded-2xl p-4 bg-gradient-to-br ${plan.gradient} border ${plan.border} ${plan.highlight ? "ring-1 ring-rose-500/20" : ""}`}
            >
              {plan.highlight && (
                <div className="absolute -top-2.5 left-1/2 -translate-x-1/2">
                  <span className="text-[10px] font-semibold px-2.5 py-0.5 rounded-full bg-rose-500 text-white">
                    Most Popular
                  </span>
                </div>
              )}

              <div className="flex items-start justify-between mb-3">
                <div>
                  <h2 className="text-sm font-semibold text-white">{plan.name}</h2>
                  <p className="text-[11px] text-white/40 mt-0.5">{plan.description}</p>
                </div>
                <div className="text-right">
                  <span className="text-lg font-bold text-white">{plan.price}</span>
                  <span className="text-white/40 text-xs">{plan.period}</span>
                </div>
              </div>

              <ul className="space-y-1.5 mb-4">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-center gap-2 text-xs text-white/65">
                    <Check className="w-3 h-3 shrink-0 text-white/40" />
                    {f}
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
          {/* Subtle aged texture */}
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
      </div>{/* end plan cards */}

      {/* Error */}
      {error && (
        <p className="text-center text-xs text-red-400 px-4 pb-4 shrink-0">{error}</p>
      )}

      {/* Footer note */}
      <p className="text-center text-[10px] text-white/20 pb-5 px-6 shrink-0">
        Payments processed securely by Stripe. Cancel anytime from your account settings.
      </p>

      <LegacyModal open={legacyModalOpen} onClose={() => setLegacyModalOpen(false)} />
    </motion.div>
  );
}
