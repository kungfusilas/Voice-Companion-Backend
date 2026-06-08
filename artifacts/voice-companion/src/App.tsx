import { useState, useEffect } from "react";
import { AnimatePresence } from "framer-motion";
import { CompanionSelect } from "@/pages/CompanionSelect";
import { ChatPage } from "@/pages/Chat";
import { AuthPage } from "@/pages/Auth";
import { PricingPage } from "@/pages/Pricing";
import { Hub } from "@/pages/Hub";
import { getSubscriptionStatus } from "@/lib/api";
import { supabase, SUPABASE_CONFIGURED } from "@/lib/supabase";
import type { Persona } from "@/lib/api";
import type { Session } from "@supabase/supabase-js";

type Screen = "loading" | "auth" | "companion-select" | "chat" | "pricing" | "hub";

const CARD_STYLE: React.CSSProperties = {
  background: "rgba(255,255,255,0.03)",
  backdropFilter: "blur(20px)",
  border: "1px solid rgba(255,255,255,0.08)",
  boxShadow: "0 30px 80px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.06)",
};

const BG_STYLE: React.CSSProperties = {
  background: "linear-gradient(145deg, #0d0d1a 0%, #0f0720 50%, #0d0d1a 100%)",
};

export default function App() {
  const [screen, setScreen] = useState<Screen>("loading");
  const [session, setSession] = useState<Session | null>(null);
  const [persona, setPersona] = useState<Persona | null>(null);
  const [relType, setRelType] = useState<string | null>(null);
  const [subscriptionTier, setSubscriptionTier] = useState("free");
  const [checkoutMessage, setCheckoutMessage] = useState<string | null>(null);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);

  // ── Auth session management ──────────────────────────────────────────────
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);

    // Check for checkout result URL params (Stripe redirect back)
    if (params.get("checkout") === "success") {
      const plan = params.get("plan");
      setCheckoutMessage(plan ? `🎉 You're on ${plan.charAt(0).toUpperCase() + plan.slice(1)}!` : "🎉 Subscription activated!");
      window.history.replaceState({}, "", window.location.pathname);
    } else if (params.get("checkout") === "cancelled") {
      window.history.replaceState({}, "", window.location.pathname);
    }

    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setScreen(session ? "companion-select" : "auth");
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
      if (session) {
        setScreen((prev) =>
          prev === "auth" || prev === "loading" ? "companion-select" : prev
        );
        // Fetch subscription tier whenever session changes
        getSubscriptionStatus().then(({ tier }) => setSubscriptionTier(tier)).catch(() => {});
      } else {
        setPersona(null);
        setRelType(null);
        setSubscriptionTier("free");
        setScreen("auth");
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  // Fetch subscription tier on mount when session exists
  useEffect(() => {
    if (session) {
      getSubscriptionStatus().then(({ tier }) => setSubscriptionTier(tier)).catch(() => {});
    }
  }, [session?.user.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const userId = session?.user.id ?? null;

  const handleCompanionSelect = (p: Persona) => {
    setPersona(p);
    setRelType("friendship");
    setScreen("chat");
  };

  const handleBack = () => {
    setPersona(null);
    setRelType(null);
    setScreen("companion-select");
  };

  const handleSignOut = async () => {
    await supabase.auth.signOut();
  };

  const handleOpenHub = () => setScreen("hub");

  const handleStartChatFromMemory = (prompt: string) => {
    setPendingPrompt(prompt);
    if (persona) {
      setScreen("chat");
    } else {
      setScreen("companion-select");
    }
  };

  // ── Missing env-var guard (dev only) ─────────────────────────────────────
  if (!SUPABASE_CONFIGURED) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6" style={BG_STYLE}>
        <div className="max-w-sm text-center space-y-4">
          <div className="text-3xl">⚙️</div>
          <h2 className="text-white text-lg font-semibold">Supabase not configured</h2>
          <p className="text-white/50 text-sm leading-relaxed">
            Add these two Replit secrets to finish auth setup:
          </p>
          <div className="text-left rounded-xl bg-white/05 border border-white/10 p-4 space-y-1 font-mono text-xs text-white/70">
            <div>VITE_SUPABASE_URL</div>
            <div>VITE_SUPABASE_ANON_KEY</div>
          </div>
          <p className="text-white/30 text-xs">
            Find these in your Supabase project under Settings → API
          </p>
        </div>
      </div>
    );
  }

  // ── Auth screen (full-page, no card wrapper) ──────────────────────────────
  if (screen === "auth") {
    return <AuthPage onAuth={() => setScreen("companion-select")} />;
  }

  // ── Hub (full-page, no card wrapper) ─────────────────────────────────────
  if (screen === "hub") {
    return (
      <Hub
        onBack={() => setScreen("companion-select")}
        userId={userId ?? ""}
        currentPersona={persona}
        onStartChat={handleStartChatFromMemory}
      />
    );
  }

  // ── Initial load spinner ──────────────────────────────────────────────────
  if (screen === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center" style={BG_STYLE}>
        <div className="w-6 h-6 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // ── Main app card ─────────────────────────────────────────────────────────
  const isNarrow = screen === "companion-select" || screen === "pricing";
  const maxW = isNarrow ? "max-w-sm" : "max-w-md";
  const h = isNarrow ? "min-h-[640px]" : "h-[680px]";

  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={BG_STYLE}>
      <div
        className={`w-full ${maxW} ${h} flex flex-col rounded-3xl overflow-hidden relative`}
        style={CARD_STYLE}
      >
        {/* Checkout success banner */}
        <AnimatePresence>
          {checkoutMessage && (
            <div
              className="absolute top-0 inset-x-0 z-10 flex items-center justify-between px-4 py-2.5 text-xs font-medium text-emerald-300"
              style={{ background: "rgba(16,185,129,0.12)", borderBottom: "1px solid rgba(16,185,129,0.2)" }}
            >
              <span>{checkoutMessage}</span>
              <button onClick={() => setCheckoutMessage(null)} className="text-emerald-400/60 hover:text-emerald-300 ml-2">✕</button>
            </div>
          )}
        </AnimatePresence>

        <AnimatePresence mode="wait">
          {screen === "companion-select" && (
            <CompanionSelect
              key="companion-select"
              onSelect={handleCompanionSelect}
              onSignOut={handleSignOut}
              onUpgrade={() => setScreen("pricing")}
              onHub={handleOpenHub}
              subscriptionTier={subscriptionTier}
            />
          )}

          {screen === "pricing" && (
            <PricingPage
              key="pricing"
              currentTier={subscriptionTier}
              onBack={() => setScreen("companion-select")}
            />
          )}

          {screen === "chat" && persona && userId && (
            <ChatPage
              key={`chat-${persona.id}`}
              persona={persona}
              relType={relType ?? "friendship"}
              userId={userId}
              onBack={handleBack}
              onChangeRelType={handleBack}
              initialMessage={pendingPrompt ?? undefined}
              onMessageConsumed={() => setPendingPrompt(null)}
            />
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
