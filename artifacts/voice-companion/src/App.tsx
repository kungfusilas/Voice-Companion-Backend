import { useState } from "react";
import { AnimatePresence } from "framer-motion";
import { PersonaSetup } from "@/components/PersonaSetup";
import { ChatPage } from "@/pages/Chat";
import type { Persona } from "@/lib/api";

export default function App() {
  const [persona, setPersona] = useState<Persona | null>(null);

  return (
    <div
      className="min-h-screen flex items-center justify-center p-4"
      style={{
        background: "linear-gradient(145deg, #0d0d1a 0%, #0f0720 50%, #0d0d1a 100%)",
      }}
    >
      <div
        className="w-full max-w-md h-[680px] flex flex-col rounded-3xl overflow-hidden relative"
        style={{
          background: "rgba(255,255,255,0.03)",
          backdropFilter: "blur(20px)",
          border: "1px solid rgba(255,255,255,0.08)",
          boxShadow: "0 30px 80px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.06)",
        }}
      >
        <AnimatePresence mode="wait">
          {!persona ? (
            <div key="setup" className="flex-1 overflow-y-auto p-6 scrollbar-thin scrollbar-thumb-white/10">
              <PersonaSetup onCreated={setPersona} />
            </div>
          ) : (
            <ChatPage
              key={`chat-${persona.id}`}
              persona={persona}
              onBack={() => setPersona(null)}
            />
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
