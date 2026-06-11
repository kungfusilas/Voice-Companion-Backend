import { useState, useEffect } from "react";
import { AnimatePresence } from "framer-motion";
import { CompanionSelect } from "@/pages/CompanionSelect";
import { ChatPage } from "@/pages/Chat";
import { AuthPage } from "@/pages/Auth";
import { AuthCallback } from "@/pages/AuthCallback";
import { PricingPage } from "@/pages/Pricing";
import { Hub } from "@/pages/Hub";
import { getSubscriptionStatus, registerSession } from "@/lib/api";
import { supabase, SUPABASE_CONFIGURED } from "@/lib/supabase";
import type { Persona } from "@/lib/api";
import type { Session } from "@supabase/supabase-js";

type Screen = "loading" | "companion-select" | "chat" | "auth" | "pricing" | "hub" | "callback";

const CARD_STYLE: React.CSSProperties = {
  background: "rgba(255,255,255,0.03)",
  backdropFilter: "blur(20px)",
  border: "1px solid rgba(255,255,255,0.08)",
  boxShadow: "0 30px 80px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.06)",
};

const BG_STYLE: React.CSSProperties = {
  background: "linear-gradient(145deg, #0d0d1a 0%, #0f0720 50%, #0d0d1a 100%)",
};

function formatPlanLabel(planKey: string): string {
  if (!planKey) return "";
  if (planKey.endsWith("_5year")) {
    const tier = planKey.slice(0, -6);
    return `${tier.charAt(0).toUpperCase() + tier.slice(1)} (5-Year)`;
  }
  if (planKey.endsWith("_annual")) {
    const tier = planKey.slice(0, -7);
    return `${tier.charAt(0).toUpperCase() + tier.slice(1)} (Annual)`;
  }
  return planKey.charAt(0).toUpperCase() + planKey.slice(1);
}

export default function App() {
  const [screen, setScreen] = useState<Screen>(() =>
    new URLSearchParams(window.location.search).get("code") ? "callback" : "loading"
  );
  const [session, setSession] = useState<Session | null>(null);
  const [persona, setPersona] = useState<Persona | null>(null);
  const [guestId, setGuestId] = useState<string | null>(null);
  const [subscriptionTier, setSubscriptionTier] = useState("free");
  const [subscriptionStatus, setSubscriptionStatus] = useState("inactive");
  const [subscribedAt, setSubscribedAt] = useState<string | null>(null);
  const [billingPeriod, setBillingPeriod] = useState("monthly");
  const [accessExpiresAt, setAccessExpiresAt] = useState<string | null>(null);
  const [subCheckDone, setSubCheckDone] = useState(false);
  const [checkoutMessage, setCheckoutMessage] = useState<string | null>(null);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);

  // ── Auth session management ──────────────────────────────────────────────
  useEffect(() => {
    // Check for Stripe checkout return params and signin deep-link
    const params = new URLSearchParams(window.location.search);
    const shouldSignIn = params.get("signin") === "1";
    if (params.get("checkout") === "success") {
      const plan = params.get("plan") ?? "";
      const label = formatPlanLabel(plan);
      setCheckoutMessage(label ? `🎉 You're on ${label}!` : "🎉 Subscription activated!");
      window.history.replaceState({}, "", window.location.pathname);
    } else if (params.get("checkout") === "cancelled") {
      window.history.replaceState({}, "", window.location.pathname);
    } else if (shouldSignIn) {
      window.history.replaceState({}, "", window.location.pathname);
    }

    // Load existing guest ID
    const existingGuestId = localStorage.getItem("bondai_guest_id");
    if (existingGuestId) setGuestId(existingGuestId);

    // If this is an OAuth callback (?code= present), skip getSession — there is
    // no session yet (the code needs to be exchanged first). AuthCallback handles
    // the exchange; onAuthStateChange below picks up the result.
    const oauthCode = params.get("code");
    if (!oauthCode) {
      // On load: resolve session then check subscription before deciding screen
      supabase.auth.getSession()
        .then(async ({ data: { session } }) => {
          setSession(session);
          if (session) {
            let sid = sessionStorage.getItem("bondai_session_id");
            if (!sid) { sid = crypto.randomUUID(); sessionStorage.setItem("bondai_session_id", sid); }
            registerSession(sid).catch(() => {});
            try {
              const { tier, status, subscribedAt, billingPeriod, accessExpiresAt } = await getSubscriptionStatus();
              setSubscriptionTier(tier);
              setSubscriptionStatus(status);
              setSubscribedAt(subscribedAt);
              setBillingPeriod(billingPeriod);
              setAccessExpiresAt(accessExpiresAt);
            } catch {
              // Subscription check failed — fail open (treat as unpaid, show pricing)
            } finally {
              setSubCheckDone(true);
            }
            setScreen("companion-select");
          } else {
            // Guest — go to auth if ?signin=1 was in the URL, else companion-select
            setScreen(shouldSignIn ? "auth" : "companion-select");
          }
        })
        .catch(() => {
          // Supabase unavailable on load — still show the app, just as guest
          setScreen(shouldSignIn ? "auth" : "companion-select");
        });
    }

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
      if (newSession) {
        // Signed in — clear guest state, register session ID, fetch tier
        setGuestId(null);
        localStorage.removeItem("bondai_guest_id");
        let sid = sessionStorage.getItem("bondai_session_id");
        if (!sid) { sid = crypto.randomUUID(); sessionStorage.setItem("bondai_session_id", sid); }
        registerSession(sid).catch(() => {});
        setSubCheckDone(false);
        getSubscriptionStatus().then(({ tier, status, subscribedAt, billingPeriod, accessExpiresAt }) => {
          setSubscriptionTier(tier);
          setSubscriptionStatus(status);
          setSubscribedAt(subscribedAt);
          setBillingPeriod(billingPeriod);
          setAccessExpiresAt(accessExpiresAt);
          setSubCheckDone(true);
        }).catch(() => {
          setSubCheckDone(true); // fail open — effectiveScreen will show pricing
        });
        // Navigate to companion-select from auth, loading, or callback screens
        setScreen((prev) => prev === "auth" || prev === "loading" || prev === "callback" ? "companion-select" : prev);
      } else {
        // Signed out (or INITIAL_SESSION with no prior session).
        // Do NOT override "callback" — the INITIAL_SESSION fires with null
        // immediately on listener registration, before the ?code= exchange
        // completes. Overriding "callback" here would unmount AuthCallback
        // before exchangeCodeForSession runs, leaving the user as a guest.
        sessionStorage.removeItem("bondai_session_id");
        setPersona(null);
        setSubscriptionTier("free");
        setSubscriptionStatus("inactive");
        setBillingPeriod("monthly");
        setAccessExpiresAt(null);
        setSubCheckDone(false);
        setScreen((prev) => prev === "callback" ? prev : "companion-select");
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  // ── User ID (real or guest) ──────────────────────────────────────────────
  const userId = session?.user.id ?? (guestId ? `guest_${guestId}` : null);
  const isGuest = !session;

  // ── Paywall: resolve which screen to actually render ─────────────────────
  // Authenticated users must have an active paid subscription to access
  // companion features. While the sub check is still in-flight we show a
  // spinner; once done, unpaid users are forced to the pricing screen.
  // 5-year users have subscription_status="active" set by the backend
  // (downgraded server-side once access_expires_at passes), so the existing
  // check covers them without any special-casing here.
  const effectiveScreen: Screen = (() => {
    if (screen === "loading") return "loading";
    if (screen === "callback") return "callback";  // OAuth callback — always bypass paywall
    if (screen === "auth") return "auth";          // always reachable
    if (screen === "pricing") return "pricing";    // always reachable
    if (session) {
      if (!subCheckDone) return "loading";         // waiting for sub check
      const isPaid = subscriptionTier !== "free" && subscriptionStatus === "active";
      if (!isPaid) return "pricing";               // gate unpaid authenticated users
    }
    return screen;
  })();

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

  // ── OAuth callback — exchanges the ?code= for a session ─────────────────
  if (effectiveScreen === "callback") {
    return (
      <AuthCallback
        onSuccess={() => {
          // onAuthStateChange fires first and transitions screen to
          // companion-select; this is a safety fallback.
          setScreen("companion-select");
        }}
        onError={() => setScreen("auth")}
      />
    );
  }

  // ── Auth screen — shown post-upgrade, not at entry ─────────────────────
  if (effectiveScreen === "auth") {
    return (
      <AuthPage
        onAuth={() => setScreen("companion-select")}
      />
    );
  }

  // ── Hub (full-page, authenticated only) ───────────────────────────────
  if (effectiveScreen === "hub") {
    return (
      <Hub
        onBack={() => setScreen("companion-select")}
        userId={userId ?? ""}
        currentPersona={persona}
        onStartChat={handleStartChatFromMemory}
        subscriptionTier={subscriptionTier}
        subscribedAt={subscribedAt}
      />
    );
  }

  // ── Initial load / subscription check spinner ─────────────────────────
  if (effectiveScreen === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center" style={BG_STYLE}>
        <div className="w-6 h-6 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // ── Main app card ─────────────────────────────────────────────────────
  const isNarrow = effectiveScreen === "companion-select" || effectiveScreen === "pricing";
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
          {effectiveScreen === "companion-select" && (
            <CompanionSelect
              key="companion-select"
              onSelect={handleCompanionSelect}
              onSignOut={session ? handleSignOut : undefined}
              onSignIn={!session ? () => setScreen("auth") : undefined}
              onUpgrade={() => setScreen("pricing")}
              onHub={session ? handleOpenHub : undefined}
              subscriptionTier={subscriptionTier}
            />
          )}

          {effectiveScreen === "pricing" && (
            <PricingPage
              key="pricing"
              currentTier={subscriptionTier}
              currentBillingPeriod={billingPeriod}
              accessExpiresAt={accessExpiresAt}
              onBack={() => setScreen("companion-select")}
              isGuest={isGuest}
              onSignIn={() => setScreen("auth")}
            />
          )}

          {effectiveScreen === "chat" && persona && userId && (
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
