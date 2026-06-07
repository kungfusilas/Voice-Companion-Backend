import { useState, useEffect } from "react";
import { AnimatePresence } from "framer-motion";
import { CompanionSelect } from "@/pages/CompanionSelect";
import { RelationshipSelect } from "@/pages/RelationshipSelect";
import { ChatPage } from "@/pages/Chat";
import { getOrCreateUserId, getRelationshipStats } from "@/lib/api";
import type { Persona } from "@/lib/api";

type Screen = "companion-select" | "rel-type-loading" | "rel-type-select" | "chat";

const USER_ID = getOrCreateUserId();

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
  const [screen, setScreen] = useState<Screen>("companion-select");
  const [persona, setPersona] = useState<Persona | null>(null);
  const [relType, setRelType] = useState<string | null>(null);

  // After companion is picked, check if they already have a relationship type
  useEffect(() => {
    if (!persona || screen !== "rel-type-loading") return;
    let cancelled = false;
    getRelationshipStats(USER_ID, persona.id)
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
  }, [persona, screen]);

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
            <CompanionSelect key="companion-select" onSelect={handleCompanionSelect} />
          )}

          {screen === "rel-type-loading" && (
            <div key="loading" className="flex flex-col items-center justify-center flex-1 gap-3">
              <div className="w-6 h-6 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
              <p className="text-white/40 text-sm">Loading…</p>
            </div>
          )}

          {screen === "rel-type-select" && persona && (
            <RelationshipSelect
              key="rel-type-select"
              persona={persona}
              userId={USER_ID}
              onSelect={handleRelTypeSelect}
              onBack={handleBack}
            />
          )}

          {screen === "chat" && persona && relType && (
            <ChatPage
              key={`chat-${persona.id}`}
              persona={persona}
              relType={relType}
              userId={USER_ID}
              onBack={handleBack}
              onChangeRelType={handleBackToRelSelect}
            />
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
