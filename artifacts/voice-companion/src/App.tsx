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

type Screen = "loading" | "companion-select" | "chat" | "auth" | "pricing" | "hub";

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
  const [guestId, setGuestId] = useState<string | null>(null);
  const [subscriptionTier, setSubscriptionTier] = useState("free");
  const [checkoutMessage, setCheckoutMessage] = useState<string | null>(null);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);

  // ── Auth session management ──────────────────────────────────────────────
  useEffect(() => {
    // Check for Stripe checkout return params
    const params = new URLSearchParams(window.location.search);
    if (params.get("checkout") === "success") {
      const plan = params.get("plan");
      setCheckoutMessage(plan ? `🎉 You're on ${plan.charAt(0).toUpperCase() + plan.slice(1)}!` : "🎉 Subscription activated!");
      window.history.replaceState({}, "", window.location.pathname);
    } else if (params.get("checkout") === "cancelled") {
      window.history.replaceState({}, "", window.location.pathname);
    }

    // Load existing guest ID
    const existingGuestId = localStorage.getItem("bondai_guest_id");
    if (existingGuestId) setGuestId(existingGuestId);

    // Always start at companion-select — no login wall
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setScreen("companion-select");
      if (session) {
        getSubscriptionStatus().then(({ tier }) => setSubscriptionTier(tier)).catch(() => {});
      }
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
      if (session) {
        // Signed in — clear guest state, fetch tier
        setGuestId(null);
        localStorage.removeItem("bondai_guest_id");
        getSubscriptionStatus().then(({ tier }) => setSubscriptionTier(tier)).catch(() => {});
        // If on auth screen, go back to companion select
        setScreen((prev) => prev === "auth" || prev === "loading" ? "companion-select" : prev);
      } else {
        // Signed out — go to companion-select (not auth)
        setPersona(null);
        setSubscriptionTier("free");
        setScreen("companion-select");
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  // ── User ID (real or guest) ──────────────────────────────────────────────
  const userId = session?.user.id ?? (guestId ? `guest_${guestId}` : null);
  const isGuest = !session;

  // ── Companion selection ──────────────────────────────────────────────────
  const handleCompanionSelect = (p: Persona) => {
    setPersona(p);
    // Ensure a guest ID exists for unauthenticated users
    if (!session) {
      let gid = localStorage.getItem("bondai_guest_id");
      if (!gid) {
        gid = crypto.randomUUID();
        localStorage.setItem("bondai_guest_id", gid);
      }
      setGuestId(gid);
    }
    setScreen("chat");
  };

  const handleBack = () => {
    setPersona(null);
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

  // ── Upgrade / subscription flow ──────────────────────────────────────────
  const handleUpgradeChoice = (tier: "free" | "premium") => {
    if (tier === "premium") {
      setScreen("pricing");
    } else {
      setScreen("auth"); // account creation for free tier
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

  // ── Auth screen — shown post-upgrade, not at entry ─────────────────────
  if (screen === "auth") {
    return (
      <AuthPage
        onAuth={() => setScreen("companion-select")}
      />
    );
  }

  // ── Hub (full-page, authenticated only) ───────────────────────────────
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

  // ── Initial load spinner ──────────────────────────────────────────────
  if (screen === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center" style={BG_STYLE}>
        <div className="w-6 h-6 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // ── Main app card ─────────────────────────────────────────────────────
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
              onSignOut={session ? handleSignOut : undefined}
              onUpgrade={() => setScreen("pricing")}
              onHub={session ? handleOpenHub : undefined}
              subscriptionTier={subscriptionTier}
            />
          )}

          {screen === "pricing" && (
            <PricingPage
              key="pricing"
              currentTier={subscriptionTier}
              onBack={() => setScreen(isGuest ? "companion-select" : "companion-select")}
            />
          )}

          {screen === "chat" && persona && userId && (
            <ChatPage
              key={`chat-${persona.id}`}
              persona={persona}
              relType="friendship"
              userId={userId}
              onBack={handleBack}
              onChangeRelType={handleBack}
              initialMessage={pendingPrompt ?? undefined}
              onMessageConsumed={() => setPendingPrompt(null)}
              isGuest={isGuest}
              subscriptionTier={subscriptionTier}
              onUpgradeChoice={handleUpgradeChoice}
            />
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
