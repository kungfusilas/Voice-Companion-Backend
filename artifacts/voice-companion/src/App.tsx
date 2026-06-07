import { useState, useEffect } from "react";
import { AnimatePresence } from "framer-motion";
import { CompanionSelect } from "@/pages/CompanionSelect";
import { RelationshipSelect } from "@/pages/RelationshipSelect";
import { ChatPage } from "@/pages/Chat";
import { AuthPage } from "@/pages/Auth";
import { getRelationshipStats } from "@/lib/api";
import { supabase, SUPABASE_CONFIGURED } from "@/lib/supabase";
import type { Persona } from "@/lib/api";
import type { Session } from "@supabase/supabase-js";

type Screen = "loading" | "auth" | "companion-select" | "rel-type-loading" | "rel-type-select" | "chat";

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

  // ── Auth session management ──────────────────────────────────────────────
  useEffect(() => {
    // Check for existing session on mount (handles OAuth callback redirect too)
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setScreen(session ? "companion-select" : "auth");
    });

    // Listen for auth state changes (sign-in, sign-out, token refresh, OAuth)
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
      if (session) {
        setScreen((prev) =>
          prev === "auth" || prev === "loading" ? "companion-select" : prev
        );
      } else {
        // Signed out — reset all state
        setPersona(null);
        setRelType(null);
        setScreen("auth");
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  // ── After companion pick, check for existing relationship type ───────────
  const userId = session?.user.id ?? null;

  useEffect(() => {
    if (!persona || !userId || screen !== "rel-type-loading") return;
    let cancelled = false;
    getRelationshipStats(userId, persona.id)
      .then((stats) => {
        if (cancelled) return;
        if (stats.relationship_type) {
          setRelType(stats.relationship_type);
          setScreen("chat");
        } else {
          setScreen("rel-type-select");
        }
      })
      .catch(() => {
        if (!cancelled) setScreen("rel-type-select");
      });
    return () => { cancelled = true; };
  }, [persona, userId, screen]);

  const handleCompanionSelect = (p: Persona) => {
    setPersona(p);
    setRelType(null);
    setScreen("rel-type-loading");
  };

  const handleRelTypeSelect = (rt: string) => {
    setRelType(rt);
    setScreen("chat");
  };

  const handleBack = () => {
    setPersona(null);
    setRelType(null);
    setScreen("companion-select");
  };

  const handleBackToRelSelect = () => {
    setRelType(null);
    setScreen("rel-type-select");
  };

  const handleSignOut = async () => {
    await supabase.auth.signOut();
    // onAuthStateChange listener will reset state and screen to "auth"
  };

  // ── Missing env-var guard (dev only) ─────────────────────────────────────
  if (!SUPABASE_CONFIGURED) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6" style={BG_STYLE}>
        <div className="max-w-sm text-center space-y-4">
          <div className="text-3xl">⚙️</div>
          <h2 className="text-white text-lg font-semibold">Supabase not configured</h2>
          <p className="text-white/50 text-sm leading-relaxed">
            Add these three Replit secrets to finish auth setup:
          </p>
          <div className="text-left rounded-xl bg-white/05 border border-white/10 p-4 space-y-1 font-mono text-xs text-white/70">
            <div>VITE_SUPABASE_URL</div>
            <div>VITE_SUPABASE_ANON_KEY</div>
            <div>SUPABASE_JWT_SECRET</div>
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

  // ── Initial load spinner ──────────────────────────────────────────────────
  if (screen === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center" style={BG_STYLE}>
        <div className="w-6 h-6 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // ── Main app card ─────────────────────────────────────────────────────────
  const isNarrow = screen === "companion-select" || screen === "rel-type-loading" || screen === "rel-type-select";
  const maxW = isNarrow ? "max-w-sm" : "max-w-md";
  const h = isNarrow ? "min-h-[640px]" : "h-[680px]";

  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={BG_STYLE}>
      <div
        className={`w-full ${maxW} ${h} flex flex-col rounded-3xl overflow-hidden relative`}
        style={CARD_STYLE}
      >
        <AnimatePresence mode="wait">
          {screen === "companion-select" && (
            <CompanionSelect key="companion-select" onSelect={handleCompanionSelect} onSignOut={handleSignOut} />
          )}

          {screen === "rel-type-loading" && (
            <div key="loading" className="flex flex-col items-center justify-center flex-1 gap-3">
              <div className="w-6 h-6 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
              <p className="text-white/40 text-sm">Loading…</p>
            </div>
          )}

          {screen === "rel-type-select" && persona && userId && (
            <RelationshipSelect
              key="rel-type-select"
              persona={persona}
              userId={userId}
              onSelect={handleRelTypeSelect}
              onBack={handleBack}
            />
          )}

          {screen === "chat" && persona && relType && userId && (
            <ChatPage
              key={`chat-${persona.id}`}
              persona={persona}
              relType={relType}
              userId={userId}
              onBack={handleBack}
              onChangeRelType={handleBackToRelSelect}
            />
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
