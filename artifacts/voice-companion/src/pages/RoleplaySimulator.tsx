import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft,
  Send,
  StopCircle,
  CheckCircle2,
  TrendingUp,
  Lightbulb,
  Sparkles,
  Heart,
  ChevronRight,
} from "lucide-react";
import { apiFetch, apiFetchJSON } from "@/lib/api";
import { FloatingHearts } from "@/components/FloatingHearts";

// ── Types ──────────────────────────────────────────────────────────────────

interface Scenario {
  id: string;
  title: string;
  description: string;
  emoji: string;
}

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface SkillEffect {
  skill: string;
  direction: "+" | "-" | "noted";
}

interface Debrief {
  went_well: string[];
  improve: string[];
  try_next: string;
  skills_affected: SkillEffect[];
}

type Phase = "select" | "setup" | "roleplay" | "debrief";

// ── Scenario card ──────────────────────────────────────────────────────────

function ScenarioCard({
  scenario,
  onSelect,
}: {
  scenario: Scenario;
  onSelect: () => void;
}) {
  return (
    <motion.button
      whileTap={{ scale: 0.97 }}
      onClick={onSelect}
      className="w-full text-left rounded-2xl px-4 py-4 transition-all group"
      style={{
        background: "rgba(255,255,255,0.03)",
        border: "1px solid rgba(255,255,255,0.07)",
      }}
    >
      <div className="flex items-start gap-3">
        <span className="text-2xl leading-none mt-0.5 shrink-0">{scenario.emoji}</span>
        <div className="flex-1 min-w-0">
          <p className="text-white/85 text-sm font-semibold mb-1 group-hover:text-white transition-colors">
            {scenario.title}
          </p>
          <p className="text-white/35 text-xs leading-relaxed">{scenario.description}</p>
        </div>
        <ChevronRight className="w-4 h-4 text-white/20 group-hover:text-white/50 transition-colors mt-0.5 shrink-0" />
      </div>
    </motion.button>
  );
}

// ── Chat bubble ────────────────────────────────────────────────────────────

function Bubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "text-white"
            : "text-white/85"
        }`}
        style={
          isUser
            ? { background: "linear-gradient(135deg, #7c3aed, #6d28d9)", borderRadius: "18px 18px 4px 18px" }
            : { background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "18px 18px 18px 4px" }
        }
      >
        {msg.content}
      </div>
    </motion.div>
  );
}

// ── Debrief section ────────────────────────────────────────────────────────

function DebriefSection({
  icon: Icon,
  label,
  color,
  bg,
  border,
  children,
}: {
  icon: React.ElementType;
  label: string;
  color: string;
  bg: string;
  border: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl px-4 py-4" style={{ background: bg, border: `1px solid ${border}` }}>
      <div className="flex items-center gap-2 mb-3">
        <Icon className={`w-4 h-4 ${color}`} />
        <span className={`text-xs font-semibold uppercase tracking-wider ${color}`}>{label}</span>
      </div>
      {children}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export function RoleplaySimulator() {
  const [phase, setPhase] = useState<Phase>("select");
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState<Scenario | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [setupQuestion, setSetupQuestion] = useState("");
  const [setupAnswer, setSetupAnswer] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [ending, setEnding] = useState(false);
  const [debrief, setDebrief] = useState<Debrief | null>(null);
  const [showHearts, setShowHearts] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Load scenarios on mount
  useEffect(() => {
    apiFetchJSON<{ scenarios: Scenario[] }>("/companion/api/roleplay/scenarios")
      .then((d) => setScenarios(d.scenarios))
      .catch(() => {});
  }, []);

  // Auto-scroll chat
  useEffect(() => {
    if (phase === "roleplay") {
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, phase]);

  // ── Handlers ─────────────────────────────────────────────────────────────

  const handleSelectScenario = async (scenario: Scenario) => {
    setSelected(scenario);
    setError(null);
    try {
      const data = await apiFetchJSON<{ session_id: string; setup_question: string }>(
        "/companion/api/roleplay/start",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scenario_id: scenario.id }),
        }
      );
      setSessionId(data.session_id);
      setSetupQuestion(data.setup_question);
      setPhase("setup");
    } catch {
      setError("Could not start session. Please try again.");
    }
  };

  const handleStartSimulation = async () => {
    if (!setupAnswer.trim() || !sessionId) return;
    setSending(true);
    setError(null);
    try {
      const data = await apiFetchJSON<{ reply: string; phase: string }>(
        "/companion/api/roleplay/message",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, message: setupAnswer.trim() }),
        }
      );
      setMessages([{ role: "assistant", content: data.reply }]);
      setPhase("roleplay");
      setTimeout(() => inputRef.current?.focus(), 100);
    } catch {
      setError("Could not start the simulation. Please try again.");
    } finally {
      setSending(false);
    }
  };

  const handleSendMessage = async () => {
    const text = input.trim();
    if (!text || sending || !sessionId) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setSending(true);
    setError(null);

    try {
      const data = await apiFetchJSON<{ reply: string; phase: string }>(
        "/companion/api/roleplay/message",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, message: text }),
        }
      );
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
    } catch {
      setError("Message failed. Try again.");
    } finally {
      setSending(false);
    }
  };

  const handleEndSession = async () => {
    if (!sessionId || ending) return;
    setEnding(true);
    setError(null);
    try {
      const data = await apiFetchJSON<{ debrief: Debrief }>(
        "/companion/api/roleplay/end",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId }),
        }
      );
      setDebrief(data.debrief);
      setShowHearts(true);
      setPhase("debrief");
    } catch {
      setError("Could not generate debrief. Please try again.");
    } finally {
      setEnding(false);
    }
  };

  const handleReset = () => {
    setPhase("select");
    setSelected(null);
    setSessionId(null);
    setSetupQuestion("");
    setSetupAnswer("");
    setMessages([]);
    setInput("");
    setDebrief(null);
    setError(null);
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4 pt-2">
      {showHearts && (
        <FloatingHearts count={1} onComplete={() => setShowHearts(false)} />
      )}

      <AnimatePresence mode="wait">

        {/* ── SELECT ────────────────────────────────────────────────── */}
        {phase === "select" && (
          <motion.div
            key="select"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="space-y-3"
          >
            <div className="pb-1">
              <p className="text-white/35 text-xs leading-relaxed">
                Choose a scenario, answer a quick setup question, and practice the real conversation
                with LegacyBond AI fully in character. Earn a ❤️ for completing each simulation.
              </p>
            </div>

            {error && <p className="text-red-400/70 text-xs text-center">{error}</p>}

            {scenarios.length === 0 ? (
              <div className="flex items-center justify-center py-10">
                <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : (
              scenarios.map((s) => (
                <ScenarioCard
                  key={s.id}
                  scenario={s}
                  onSelect={() => handleSelectScenario(s)}
                />
              ))
            )}
          </motion.div>
        )}

        {/* ── SETUP ─────────────────────────────────────────────────── */}
        {phase === "setup" && selected && (
          <motion.div
            key="setup"
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -16 }}
            className="space-y-5"
          >
            {/* Back */}
            <button
              onClick={handleReset}
              className="flex items-center gap-1 text-white/35 hover:text-white/60 text-xs transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              Choose different scenario
            </button>

            {/* Scenario header */}
            <div
              className="rounded-2xl px-4 py-4"
              style={{ background: "rgba(139,92,246,0.08)", border: "1px solid rgba(139,92,246,0.18)" }}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xl">{selected.emoji}</span>
                <span className="text-white/90 text-sm font-semibold">{selected.title}</span>
              </div>
              <p className="text-white/40 text-xs leading-relaxed">{selected.description}</p>
            </div>

            {/* Setup question */}
            <div className="space-y-3">
              <div className="flex items-start gap-2">
                <div
                  className="w-6 h-6 rounded-full flex items-center justify-center shrink-0 mt-0.5"
                  style={{ background: "rgba(139,92,246,0.2)", border: "1px solid rgba(139,92,246,0.3)" }}
                >
                  <Sparkles className="w-3 h-3 text-violet-400" />
                </div>
                <p className="text-white/75 text-sm leading-relaxed">{setupQuestion}</p>
              </div>

              <textarea
                autoFocus
                value={setupAnswer}
                onChange={(e) => setSetupAnswer(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleStartSimulation();
                  }
                }}
                placeholder="Type your answer here…"
                rows={3}
                className="w-full px-4 py-3 rounded-xl text-white placeholder-white/25 text-sm leading-relaxed focus:outline-none focus:border-violet-500/50 transition-colors resize-none"
                style={{
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.10)",
                }}
              />

              {error && <p className="text-red-400/70 text-xs">{error}</p>}

              <button
                onClick={handleStartSimulation}
                disabled={!setupAnswer.trim() || sending}
                className="w-full py-3 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-40"
                style={{
                  background: "linear-gradient(135deg, #7c3aed, #6d28d9)",
                  boxShadow: setupAnswer.trim() ? "0 4px 16px rgba(124,58,237,0.35)" : "none",
                }}
              >
                {sending ? (
                  <span className="flex items-center justify-center gap-2">
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Starting simulation…
                  </span>
                ) : (
                  "Start Simulation →"
                )}
              </button>
            </div>
          </motion.div>
        )}

        {/* ── ROLEPLAY ──────────────────────────────────────────────── */}
        {phase === "roleplay" && selected && (
          <motion.div
            key="roleplay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col"
            style={{ height: "calc(100vh - 200px)", minHeight: 400 }}
          >
            {/* Roleplay header */}
            <div
              className="flex items-center justify-between px-4 py-3 rounded-2xl mb-4 shrink-0"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}
            >
              <div className="flex items-center gap-2">
                <span className="text-base">{selected.emoji}</span>
                <div>
                  <p className="text-white/80 text-xs font-semibold">{selected.title}</p>
                  <p className="text-white/30 text-[10px]">Simulation in progress</p>
                </div>
              </div>
              <button
                onClick={handleEndSession}
                disabled={ending}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium text-red-400/80 hover:text-red-400 transition-colors border border-red-500/20 hover:border-red-500/40"
                style={{ background: "rgba(239,68,68,0.05)" }}
              >
                <StopCircle className="w-3.5 h-3.5" />
                {ending ? "Generating debrief…" : "End Session"}
              </button>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto space-y-3 pb-4">
              {messages.map((m, i) => (
                <Bubble key={i} msg={m} />
              ))}
              {sending && (
                <div className="flex justify-start">
                  <div
                    className="px-4 py-3 rounded-2xl flex items-center gap-1.5"
                    style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "18px 18px 18px 4px" }}
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-white/40 animate-bounce" style={{ animationDelay: "0ms" }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-white/40 animate-bounce" style={{ animationDelay: "120ms" }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-white/40 animate-bounce" style={{ animationDelay: "240ms" }} />
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Input */}
            <div className="shrink-0 pt-2">
              {error && <p className="text-red-400/70 text-xs mb-2 text-center">{error}</p>}
              <div className="flex gap-2 items-end">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSendMessage();
                    }
                  }}
                  placeholder="Your response…"
                  rows={1}
                  className="flex-1 px-4 py-3 rounded-xl text-white placeholder-white/25 text-sm focus:outline-none focus:border-violet-500/40 transition-colors resize-none"
                  style={{
                    background: "rgba(255,255,255,0.05)",
                    border: "1px solid rgba(255,255,255,0.10)",
                    maxHeight: 120,
                  }}
                  onInput={(e) => {
                    const el = e.currentTarget;
                    el.style.height = "auto";
                    el.style.height = Math.min(el.scrollHeight, 120) + "px";
                  }}
                />
                <button
                  onClick={handleSendMessage}
                  disabled={!input.trim() || sending}
                  className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0 transition-all disabled:opacity-40"
                  style={{ background: "linear-gradient(135deg, #7c3aed, #6d28d9)" }}
                >
                  <Send className="w-4 h-4 text-white" />
                </button>
              </div>
            </div>
          </motion.div>
        )}

        {/* ── DEBRIEF ───────────────────────────────────────────────── */}
        {phase === "debrief" && debrief && selected && (
          <motion.div
            key="debrief"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="space-y-4"
          >
            {/* Header */}
            <div className="text-center pb-2">
              <div
                className="w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-3"
                style={{ background: "rgba(139,92,246,0.15)", border: "1px solid rgba(139,92,246,0.25)" }}
              >
                <span className="text-2xl">{selected.emoji}</span>
              </div>
              <p className="text-white/90 font-bold text-base">Simulation Complete</p>
              <p className="text-white/40 text-xs mt-1">{selected.title} · Coaching Debrief</p>
            </div>

            {/* What went well */}
            <DebriefSection
              icon={CheckCircle2}
              label="What went well"
              color="text-emerald-400"
              bg="rgba(16,185,129,0.06)"
              border="rgba(16,185,129,0.15)"
            >
              <ul className="space-y-2">
                {debrief.went_well.map((item, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-emerald-400/60 text-xs mt-0.5 shrink-0">✓</span>
                    <p className="text-white/75 text-xs leading-relaxed">{item}</p>
                  </li>
                ))}
              </ul>
            </DebriefSection>

            {/* Moments to improve */}
            <DebriefSection
              icon={TrendingUp}
              label="Moments to improve"
              color="text-amber-400"
              bg="rgba(251,191,36,0.06)"
              border="rgba(251,191,36,0.15)"
            >
              <ul className="space-y-2">
                {debrief.improve.map((item, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-amber-400/60 text-xs mt-0.5 shrink-0">→</span>
                    <p className="text-white/75 text-xs leading-relaxed">{item}</p>
                  </li>
                ))}
              </ul>
            </DebriefSection>

            {/* Try next time */}
            <DebriefSection
              icon={Lightbulb}
              label="Try next time"
              color="text-sky-400"
              bg="rgba(56,189,248,0.06)"
              border="rgba(56,189,248,0.15)"
            >
              <p className="text-white/75 text-xs leading-relaxed">{debrief.try_next}</p>
            </DebriefSection>

            {/* Skills affected */}
            {debrief.skills_affected?.length > 0 && (
              <div
                className="rounded-2xl px-4 py-4"
                style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
              >
                <p className="text-white/30 text-[10px] uppercase tracking-wider font-medium mb-3">
                  Bond Score Skills Affected
                </p>
                <div className="flex flex-wrap gap-2">
                  {debrief.skills_affected.map((s, i) => (
                    <span
                      key={i}
                      className="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium"
                      style={{
                        background:
                          s.direction === "+"
                            ? "rgba(16,185,129,0.10)"
                            : s.direction === "-"
                            ? "rgba(239,68,68,0.10)"
                            : "rgba(139,92,246,0.10)",
                        border:
                          s.direction === "+"
                            ? "1px solid rgba(16,185,129,0.20)"
                            : s.direction === "-"
                            ? "1px solid rgba(239,68,68,0.20)"
                            : "1px solid rgba(139,92,246,0.20)",
                        color:
                          s.direction === "+"
                            ? "rgba(52,211,153,0.9)"
                            : s.direction === "-"
                            ? "rgba(248,113,113,0.9)"
                            : "rgba(196,181,253,0.85)",
                      }}
                    >
                      {s.direction === "+" ? "↑" : s.direction === "-" ? "↓" : "·"} {s.skill}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Heart earned */}
            <div
              className="flex items-center justify-center gap-2 py-3 rounded-2xl"
              style={{ background: "rgba(239,68,68,0.06)", border: "1px solid rgba(239,68,68,0.12)" }}
            >
              <Heart className="w-4 h-4 text-red-400/70" />
              <span className="text-white/50 text-xs">+1 heart earned for completing this simulation</span>
            </div>

            {/* Actions */}
            <div className="flex gap-2 pt-1">
              <button
                onClick={handleReset}
                className="flex-1 py-3 rounded-xl text-sm font-semibold text-white/60 hover:text-white transition-colors border border-white/10 hover:border-white/20"
                style={{ background: "rgba(255,255,255,0.03)" }}
              >
                Try Another
              </button>
              <button
                onClick={handleReset}
                className="flex-1 py-3 rounded-xl text-sm font-semibold text-white transition-all"
                style={{ background: "linear-gradient(135deg, #7c3aed, #6d28d9)" }}
              >
                Done
              </button>
            </div>
          </motion.div>
        )}

      </AnimatePresence>
    </div>
  );
}
