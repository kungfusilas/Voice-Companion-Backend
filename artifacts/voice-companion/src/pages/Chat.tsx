import { useState, useCallback, useRef, useId, useEffect } from "react";
import { supabase } from "@/lib/supabase";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, Volume2, VolumeX, Camera, Loader2, Moon } from "lucide-react";
import { Avatar } from "@/components/Avatar";
import { ChatTranscript } from "@/components/ChatTranscript";
import { ConnectionMeter } from "@/components/ConnectionMeter";
import { PushToTalkButton } from "@/components/PushToTalkButton";
import { TextInput } from "@/components/TextInput";
import { MemoriesPanel } from "@/components/MemoriesPanel";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";
import { useAudioPlayer } from "@/hooks/useAudioPlayer";
import {
  chatStream,
  transcribeAudio,
  speakText,
  fetchProactiveMessages,
  requestSelfie,
  getRelationshipStats,
  startActivity,
  setRomanticMode,
  submitWaitlist,
  requestWowMoment,
  ApiError,
  getUsageStatus,
} from "@/lib/api";
import { scoring } from "@/lib/scoring";
import type { Persona, ChatMessage, ActivityType } from "@/lib/api";
import { QuotaModal } from "@/components/QuotaModal";
import type { QuotaDetail } from "@/components/QuotaModal";

// ── Onboarding questions ──────────────────────────────────────────────────────

const ONBOARDING_QUESTIONS = [
  "What's your name?",
  "How old are you — or what stage of life are you in right now?",
  "What's been on your mind the most lately?",
  "Who are the most important people in your life right now?",
  "Is there a relationship you've been hoping to improve?",
  "What does feeling truly close to someone look like for you?",
  "What's something you wish more people understood about you?",
  "What are you working on about yourself these days?",
  "What kind of support do you find most helpful — someone who listens, or someone who challenges you?",
  "Is there anything you'd want me to always remember about you?",
];

const ONBOARDING_OPENER = `Hey! Before we get into it, I want to say something first. Most people edit themselves — even with their doctor. Not because they're bad people, just because it feels awkward or they worry about being judged. I get it. But here, I actually need the real you. The unfiltered version. I can only be genuinely useful to you if you give me that. So — no pressure, but honest answers matter here. Okay. Let's do this. What's your name?`;

function getOnboardingContext(step: number): string {
  if (step >= ONBOARDING_QUESTIONS.length) return "";
  const q = ONBOARDING_QUESTIONS[step];
  if (step === 0) {
    return `[ONBOARDING Q1/10 — KEEP IT SHORT]: The user just responded to your opener. Give ONE brief warm sentence of acknowledgment, then immediately ask: "${q}" Nothing more — no reflection, no depth, no poetry. Just the ack and the question.`;
  }
  return `[ONBOARDING Q${step + 1}/10 — KEEP IT SHORT]: Acknowledge what they just said in ONE sentence only (e.g. "Nice to meet you, [name]." / "Got it." / "That makes sense." / "I love that.") then immediately ask: "${q}" Max 2 sentences total. Save all depth and reflection for after onboarding is complete.`;
}

// ─────────────────────────────────────────────────────────────────────────────

interface ChatPageProps {
  persona: Persona;
  relType: string;
  userId: string;
  onBack: () => void;
  onChangeRelType: () => void;
  initialMessage?: string;
  onMessageConsumed?: () => void;
  isGuest?: boolean;
  subscriptionTier?: string;
  onUpgradeChoice?: (tier: "free" | "premium") => void;
}

const ACTIVITY_BUTTONS: { type: ActivityType; icon: string; label: string }[] = [
  { type: "word_game",        icon: "🔤", label: "Word Game"        },
  { type: "trivia",           icon: "🧠", label: "Trivia"           },
  { type: "would_you_rather", icon: "🤔", label: "Would You Rather" },
];

export function ChatPage({
  persona, relType, userId, onBack, onChangeRelType,
  initialMessage, onMessageConsumed,
  isGuest = false, subscriptionTier = "free", onUpgradeChoice,
}: ChatPageProps) {
  const isPremium = !isGuest && ["premium", "power", "elite"].includes(subscriptionTier);
  const isPower   = !isGuest && ["power", "elite"].includes(subscriptionTier);
  const isElite   = !isGuest && subscriptionTier === "elite";
  const rawId = useId();
  const sessionId = rawId.replace(/:/g, "s");

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [selfieLoading, setSelfieLoading] = useState(false);
  const [activityLoading, setActivityLoading] = useState<ActivityType | null>(null);
  const [error, setError] = useState("");
  const [proactiveLabel, setProactiveLabel] = useState<string | null>(null);

  const [connectionScore, setConnectionScore] = useState(50);
  const [stageName, setStageName] = useState("");
  const [stageMin, setStageMin] = useState(0);
  const [stageMax, setStageMax] = useState(100);
  const [scoreDelta, setScoreDelta] = useState<number | undefined>(undefined);

  // Romantic mode — persisted in localStorage, premium only
  const rmKey = `romantic_mode_${userId}_${persona.id}`;
  const ruKey = `romantic_unlocked_${userId}_${persona.id}`;
  const [romanticMode, setRomanticModeState] = useState(
    () => isPremium && localStorage.getItem(rmKey) === "true"
  );
  const [romanticUnlocked, setRomanticUnlocked] = useState(
    () => isPremium && localStorage.getItem(ruKey) === "true"
  );
  const [showAgeGate, setShowAgeGate] = useState(false);
  const [romanticLoading, setRomanticLoading] = useState(false);

  const [waitlistPrompt, setWaitlistPrompt] = useState<string | null>(null);
  const [waitlistSubmitted, setWaitlistSubmitted] = useState(false);
  const [waitlistEmail, setWaitlistEmail] = useState("");
  const [waitlistLoading, setWaitlistLoading] = useState(false);

  // Guest onboarding state — refs to avoid stale closure issues
  // Start at 1 because Q1 ("What's your name?") is already in the opener message
  const guestMsgCountRef = useRef(isGuest ? 1 : 0);
  const wowDoneRef = useRef(false);
  const [showUpgradeCard, setShowUpgradeCard] = useState(false);
  const [wowGenerating, setWowGenerating] = useState(false);
  const [quotaErrorDetail, setQuotaErrorDetail] = useState<QuotaDetail | null>(null);

  // ── 80% usage warning — shown once per browser session ────────────────────
  useEffect(() => {
    if (isGuest) return;
    const warnKey = `usage_80pct_${userId}`;
    if (sessionStorage.getItem(warnKey)) return;
    getUsageStatus().then((status) => {
      const msgPct = status.msgs_allowance > 0
        ? status.msgs_used / (status.msgs_allowance + status.topup_msgs)
        : 0;
      const voicePct = status.voice_allowance > 0
        ? status.voice_seconds_used / (status.voice_allowance + status.topup_voice_seconds)
        : 0;
      if (Math.max(msgPct, voicePct) >= 0.8) {
        setError(`You've used ${Math.round(Math.max(msgPct, voicePct) * 100)}% of your monthly allowance.`);
        sessionStorage.setItem(warnKey, "1");
      }
    }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const busyRef = useRef(false);
  const { playing: speaking, play: playAudio } = useAudioPlayer();

  // Init meter + romantic mode from DB (skip for guests)
  useEffect(() => {
    if (isGuest) return;
    let cancelled = false;
    getRelationshipStats(userId, persona.id)
      .then((stats) => {
        if (cancelled) return;
        const score = stats.connection_score ?? 50;
        setConnectionScore(score);
        const [sName, sMin, sMax] = scoring.getStage(score, relType);
        setStageName(sName);
        setStageMin(sMin);
        setStageMax(sMax);
        if (localStorage.getItem(rmKey) === null) {
          setRomanticModeState(stats.romantic_mode ?? false);
        }
        if (localStorage.getItem(ruKey) === null) {
          setRomanticUnlocked(stats.romantic_mode_unlocked ?? false);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [persona.id, relType, userId, isGuest]); // eslint-disable-line react-hooks/exhaustive-deps

  // Guest opener — pre-load a single warm intro message before any user input
  useEffect(() => {
    if (!isGuest) return;
    setMessages([{ role: "assistant", content: ONBOARDING_OPENER }]);
    speakText(ONBOARDING_OPENER, persona.id)
      .then((url) => playAudio(url))
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Load proactive messages (skip for guests)
  useEffect(() => {
    if (isGuest) return;
    let cancelled = false;
    fetchProactiveMessages(userId, persona.id)
      .then((data) => {
        if (cancelled || !data.messages.length) return;
        const msgs: ChatMessage[] = data.messages.map((m) => ({
          role: "assistant" as const,
          content: m.message,
          proactive: true,
          activityData: m.activity_data ?? undefined,
        }));
        setMessages(msgs);
        setProactiveLabel(`💭 ${persona.name} was thinking about you while you were away`);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [persona.id, persona.name, userId, isGuest]);

  const sendMessage = useCallback(async (userText: string) => {
    if (busyRef.current || showUpgradeCard) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setProactiveLabel(null);
    setScoreDelta(undefined);
    setMessages((prev) => [...prev, { role: "user", content: userText }]);
    setStreamingText("");

    // Compute onboarding context for this step (guest flow only)
    let onboardingCtx: string | undefined;
    if (isGuest && !wowDoneRef.current) {
      const step = guestMsgCountRef.current;
      if (step < ONBOARDING_QUESTIONS.length) {
        onboardingCtx = getOnboardingContext(step);
      }
    }

    let fullReply = "";
    let shouldTriggerWow = false;

    try {
      for await (const event of chatStream(sessionId, persona.id, userText, userId, romanticMode, false, onboardingCtx)) {
        if (event.type === "token") {
          fullReply += event.text ?? "";
          setStreamingText(fullReply);
        } else if (event.type === "done") {
          fullReply = event.full_text ?? fullReply;
          setStreamingText("");
          const newMsgs: ChatMessage[] = [{ role: "assistant", content: fullReply }];
          if (event.stage_up_text) newMsgs.push({ role: "assistant", content: event.stage_up_text });
          setMessages((prev) => [...prev, ...newMsgs]);

          if (!isGuest && event.connection_score !== undefined) {
            setConnectionScore(event.connection_score);
            setScoreDelta(event.score_delta);
            setStageName(event.stage_name ?? "");
            setStageMin(event.stage_min ?? 0);
            setStageMax(event.stage_max ?? 100);
          }

          // Track guest onboarding progress BEFORE TTS so we know if this is Q10
          if (isGuest && !wowDoneRef.current) {
            guestMsgCountRef.current += 1;
            if (guestMsgCountRef.current >= 10) {
              shouldTriggerWow = true;
            }
          }

          // Inline TTS for regular messages only — wow sequence speaks Q10 explicitly
          if (ttsEnabled && fullReply && !shouldTriggerWow) {
            const spokenText = fullReply
              .replace(/\*[^*]*\*/g, "")
              .replace(/\[[^\]]*\]/g, "")
              .replace(/\([^)]*\)/g, "")
              .replace(/\s+/g, " ")
              .trim();
            if (spokenText) {
              try {
                await playAudio(await speakText(spokenText, persona.id));
              } catch (ttsErr) {
                if (ttsErr instanceof ApiError && ttsErr.status === 402) setQuotaErrorDetail(ttsErr.detail as QuotaDetail);
              }
            }
          }

        } else if (event.type === "waitlist_prompt") {
          setWaitlistPrompt(event.companion_id ?? persona.id);
        } else if (event.type === "error") {
          setError(event.message ?? "Unknown error");
          setStreamingText("");
        }
      }
    } catch (e: unknown) {
      if (e instanceof ApiError) {
        if (e.status === 402) {
          setQuotaErrorDetail(e.detail as QuotaDetail);
        } else if (e.status === 429) {
          setError((e.detail as Record<string, string> | null)?.message ?? "Hourly limit reached — try again soon.");
        } else if (e.status === 401) {
          setError("Your account was opened on another device. Please sign in again.");
        } else {
          setError(e.message);
        }
      } else {
        setError(e instanceof Error ? e.message : "Connection error");
      }
      setStreamingText("");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }

    // Shared TTS helper — resolves only when audio.onended fires
    const speakMsg = async (text: string): Promise<void> => {
      if (!ttsEnabled) return;
      const spoken = text
        .replace(/\*[^*]*\*/g, "")
        .replace(/\[[^\]]*\]/g, "")
        .replace(/\([^)]*\)/g, "")
        .replace(/\s+/g, " ")
        .trim();
      if (spoken) {
        try { await playAudio(await speakText(spoken, persona.id)); } catch {}
      }
    };

    // Wow moment: fully sequential audio chain — no overlaps
    if (shouldTriggerWow && !wowDoneRef.current) {
      wowDoneRef.current = true;

      // Step 2: await Q10 response audio before anything else starts
      await speakMsg(fullReply);

      setWowGenerating(true);
      try {
        // Step 3: fetch wow message, append, speak
        const { message: wowMsg } = await requestWowMoment(sessionId, persona.id);
        setMessages((prev) => [...prev, { role: "assistant", content: wowMsg }]);
        await speakMsg(wowMsg);                    // Step 4: await wow audio

        // Step 5: append subscription ask, speak
        const upgradeAsk = `I want to keep remembering all of this. Every conversation, every detail, every goal you share with me. Want to make this permanent?`;
        setMessages((prev) => [...prev, { role: "assistant", content: upgradeAsk }]);
        await speakMsg(upgradeAsk);                // Step 6: await subscription ask audio
        setShowUpgradeCard(true);
      } catch {
        setShowUpgradeCard(true);
      } finally {
        setWowGenerating(false);
      }
    }
  }, [sessionId, persona.id, userId, ttsEnabled, playAudio, romanticMode, isGuest, showUpgradeCard]);

  // Romantic mode toggle handler
  const handleRomanticToggle = useCallback(() => {
    if (!isPremium || romanticLoading) return;
    if (!romanticUnlocked) {
      setShowAgeGate(true);
      return;
    }
    const next = !romanticMode;
    setRomanticLoading(true);
    setRomanticMode(userId, persona.id, next)
      .then(({ companion_reaction }) => {
        setRomanticModeState(next);
        localStorage.setItem(rmKey, String(next));
        setMessages((prev) => [...prev, { role: "assistant", content: companion_reaction }]);
      })
      .catch(() => setError("Could not change romantic mode — try again"))
      .finally(() => setRomanticLoading(false));
  }, [isPremium, romanticLoading, romanticUnlocked, romanticMode, userId, persona.id, rmKey]);

  const handleAgeGateConfirm = useCallback(() => {
    setShowAgeGate(false);
    setRomanticLoading(true);
    setRomanticMode(userId, persona.id, true)
      .then(({ companion_reaction }) => {
        setRomanticModeState(true);
        setRomanticUnlocked(true);
        localStorage.setItem(rmKey, "true");
        localStorage.setItem(ruKey, "true");
        setMessages((prev) => [...prev, { role: "assistant", content: companion_reaction }]);
      })
      .catch(() => setError("Could not enable romantic mode — try again"))
      .finally(() => setRomanticLoading(false));
  }, [userId, persona.id, rmKey, ruKey]);

  const handleActivity = useCallback(async (type: ActivityType) => {
    if (activityLoading || busy || isGuest) return;
    setActivityLoading(type);
    setError("");
    try {
      const data = await startActivity(persona.id, userId, type);
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: data.companion_intro,
        activityData: data,
      }]);
    } catch {
      setError("Couldn't start activity — try again");
    } finally {
      setActivityLoading(null);
    }
  }, [persona.id, userId, activityLoading, busy, isGuest]);

  const handleWaitlistSubmit = useCallback(async () => {
    if (!waitlistEmail.trim() || !waitlistPrompt) return;
    setWaitlistLoading(true);
    try {
      await submitWaitlist(waitlistEmail.trim(), waitlistPrompt, userId);
      setWaitlistSubmitted(true);
    } catch {
      setWaitlistSubmitted(true);
    } finally {
      setWaitlistLoading(false);
    }
  }, [waitlistEmail, waitlistPrompt, userId]);

  const handleSelfie = useCallback(async () => {
    if (selfieLoading || busy || isGuest) return;
    setSelfieLoading(true);
    setError("");
    try {
      const imageUrl = await requestSelfie(persona.id, userId);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `${persona.name} sent you a photo 📸`, imageUrl },
      ]);
    } catch {
      setError("Couldn't generate selfie — try again");
    } finally {
      setSelfieLoading(false);
    }
  }, [persona.id, persona.name, userId, selfieLoading, busy, isGuest]);

  const handleAudio = useCallback(async (blob: Blob) => {
    try {
      const transcript = await transcribeAudio(blob);
      if (transcript.trim()) await sendMessage(transcript);
    } catch (sttErr) {
      if (sttErr instanceof ApiError && sttErr.status === 402) {
        setQuotaErrorDetail(sttErr.detail as QuotaDetail);
      } else {
        setError("Transcription failed — try again");
      }
    } finally {
      resetRecorder();
    }
  }, [sendMessage]); // eslint-disable-line react-hooks/exhaustive-deps

  const { state: recorderState, start, stop, reset: resetRecorder } = useVoiceRecorder(handleAudio);
  const isBusy = busy || recorderState === "processing";

  const handleBack = useCallback(() => {
    if (isPower) {
      const userMsgCount = messages.filter(m => m.role === "user").length;
      if (userMsgCount >= 3) {
        void (async () => {
          try {
            const { data: { session } } = await supabase.auth.getSession();
            const token = session?.access_token ?? "";
            if (token) {
              fetch("/companion/api/analysis/debrief", {
                method: "POST",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({ session_id: sessionId, companion_id: persona.id, companion_name: persona.name }),
                keepalive: true,
              }).catch(() => {});
            }
          } catch { /* ignore */ }
        })();
      }
    }
    onBack();
  }, [isPower, messages, sessionId, persona.id, persona.name, onBack]);

  const typeColors: Record<string, string> = {
    romance:      "border-rose-800/40 text-rose-400 hover:bg-rose-900/30",
    mentor:       "border-violet-800/40 text-violet-400 hover:bg-violet-900/30",
    friendship:   "border-teal-800/40 text-teal-400 hover:bg-teal-900/30",
    professional: "border-sky-800/40 text-sky-400 hover:bg-sky-900/30",
  };
  const accentColor = persona.nsfw_mode
    ? "border-red-800/40 text-red-400 hover:bg-red-900/30"
    : (typeColors[relType] ?? typeColors.romance);

  const inputPlaceholder = romanticMode ? `Talk to ${persona.name}…` : undefined;

  return (
    <motion.div
      initial={{ opacity: 0, x: 30 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -30 }}
      className="flex flex-col h-full"
    >
      {/* ── Header ── */}
      <div className="flex items-center justify-between px-4 pt-4 pb-2 shrink-0">
        <button
          onClick={handleBack}
          className="flex items-center gap-1.5 text-white/50 hover:text-white transition text-sm"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>
        <div className="flex items-center gap-2">
          {!isGuest && (
            <MemoriesPanel
              userId={userId}
              personaId={persona.id}
              personaName={persona.name}
              nsfw={persona.nsfw_mode}
            />
          )}

          {/* Romantic mode — premium only */}
          {isPremium && (
            <motion.button
              onClick={handleRomanticToggle}
              disabled={romanticLoading}
              title="Romantic Mode"
              className="relative flex items-center justify-center w-8 h-8 rounded-full border transition disabled:opacity-50"
              style={{
                borderColor: romanticMode ? "rgba(251,113,133,0.5)" : "rgba(255,255,255,0.12)",
                background: romanticMode ? "rgba(159,18,57,0.15)" : "rgba(255,255,255,0.04)",
              }}
              animate={romanticMode ? {
                boxShadow: [
                  "0 0 6px rgba(251,113,133,0.3)",
                  "0 0 14px rgba(251,113,133,0.6)",
                  "0 0 6px rgba(251,113,133,0.3)",
                ],
              } : { boxShadow: "none" }}
              transition={romanticMode ? { duration: 2, repeat: Infinity } : {}}
            >
              {romanticLoading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin text-rose-400" />
              ) : (
                <Moon
                  className="w-3.5 h-3.5 transition-colors"
                  style={{ color: romanticMode ? "#fb7185" : "rgba(255,255,255,0.3)" }}
                />
              )}
            </motion.button>
          )}

          <button
            onClick={() => setTtsEnabled((v) => !v)}
            className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border transition ${
              ttsEnabled
                ? "border-white/20 text-white/70 bg-white/5 hover:bg-white/10"
                : "border-white/10 text-white/30 hover:text-white/50"
            }`}
          >
            {ttsEnabled ? <Volume2 className="w-3.5 h-3.5" /> : <VolumeX className="w-3.5 h-3.5" />}
            {ttsEnabled ? "Voice on" : "Voice off"}
          </button>
        </div>
      </div>

      {/* ── Avatar ── */}
      <div className="flex justify-center py-3 shrink-0">
        <Avatar
          name={persona.name}
          personaId={persona.id}
          speaking={speaking}
          listening={recorderState === "recording"}
          nsfw={persona.nsfw_mode}
        />
      </div>

      {/* ── Backend badge ── */}
      <div className="flex justify-center mb-2 shrink-0">
        <span
          className={`text-xs px-2.5 py-0.5 rounded-full border transition ${
            isGuest ? "cursor-default" : "cursor-pointer"
          } ${
            persona.nsfw_mode
              ? "bg-red-950/40 border-red-800/40 text-red-400"
              : romanticMode
              ? "bg-rose-950/40 border-rose-800/40 text-rose-400"
              : "bg-violet-950/40 border-violet-800/40 text-violet-400"
          }`}
          onClick={isGuest ? undefined : onChangeRelType}
        >
          {persona.nsfw_mode
            ? "Venice.ai · uncensored"
            : romanticMode
            ? "Claude · romantic mode 🌙"
            : "Claude · standard"}
        </span>
      </div>

      {/* ── Connection Meter (authenticated only) ── */}
      {!isGuest && stageName && (
        <ConnectionMeter
          score={connectionScore}
          stageName={stageName}
          stageMin={stageMin}
          stageMax={stageMax}
          relType={relType}
          scoreDelta={scoreDelta}
        />
      )}

      {/* ── Proactive label ── */}
      {proactiveLabel && (
        <div className="flex justify-center px-4 mb-1 shrink-0">
          <span className="text-[11px] text-violet-300/60 italic bg-violet-950/30 border border-violet-800/20 px-3 py-1 rounded-full">
            {proactiveLabel}
          </span>
        </div>
      )}

      {/* ── Transcript ── */}
      <ChatTranscript
        messages={messages}
        streamingText={streamingText}
        personaName={persona.name}
        nsfw={persona.nsfw_mode}
        userId={userId}
        onChatContinue={sendMessage}
      />

      {/* ── Wow generating spinner ── */}
      <AnimatePresence>
        {wowGenerating && (
          <motion.div
            key="wow-spinner"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex justify-center mb-2 shrink-0"
          >
            <div className="flex items-center gap-2 text-xs text-violet-300/50 italic">
              <div className="w-3 h-3 border border-violet-400/30 border-t-violet-400 rounded-full animate-spin" />
              reflecting…
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Upgrade card (appears after wow moment) ── */}
      <AnimatePresence>
        {showUpgradeCard && !wowGenerating && (
          <motion.div
            key="upgrade-card"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1, type: "spring", stiffness: 280, damping: 26 }}
            className="mx-4 mb-3 shrink-0 space-y-2"
          >
            {/* Premium */}
            <button
              onClick={() => onUpgradeChoice?.("premium")}
              className="w-full py-4 px-4 rounded-2xl text-left transition-transform active:scale-[0.98]"
              style={{
                background: "linear-gradient(135deg, rgba(124,58,237,0.22), rgba(109,40,217,0.10))",
                border: "1px solid rgba(139,92,246,0.42)",
                boxShadow: "0 4px 24px rgba(109,40,217,0.18)",
              }}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-white font-semibold text-sm">✨ Go Premium</p>
                  <p className="text-white/40 text-xs mt-0.5">Unlimited · Full memory · Every feature</p>
                </div>
                <span className="text-violet-400 text-sm shrink-0 ml-3">→</span>
              </div>
            </button>

            {/* Free */}
            <button
              onClick={() => onUpgradeChoice?.("free")}
              className="w-full py-3 px-4 rounded-2xl text-left transition-transform active:scale-[0.98]"
              style={{
                background: "rgba(255,255,255,0.03)",
                border: "1px solid rgba(255,255,255,0.09)",
              }}
            >
              <p className="text-white/55 text-sm">Continue for free</p>
              <p className="text-white/28 text-xs mt-0.5">Limited messages · No memory between sessions</p>
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Waitlist card ── */}
      <AnimatePresence>
        {waitlistPrompt && (
          <motion.div
            key="waitlist"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            className="mx-4 mb-2 shrink-0"
          >
            {waitlistSubmitted ? (
              <div
                className="flex items-center gap-2 px-4 py-3 rounded-2xl text-sm text-emerald-400"
                style={{
                  background: "rgba(16,185,129,0.08)",
                  border: "1px solid rgba(16,185,129,0.2)",
                }}
              >
                <span>✓</span>
                <span>You&apos;re on the list</span>
              </div>
            ) : (
              <div
                className="px-4 py-3 rounded-2xl space-y-2.5"
                style={{
                  background: "rgba(139,92,246,0.07)",
                  border: "1px solid rgba(139,92,246,0.2)",
                }}
              >
                <p className="text-xs text-white/60 leading-relaxed">
                  Want to be first when <span className="text-white/80 font-medium">{persona.name}</span> unlocks? Drop your email.
                </p>
                <div className="flex gap-2">
                  <input
                    type="email"
                    value={waitlistEmail}
                    onChange={(e) => setWaitlistEmail(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && waitlistEmail.trim()) handleWaitlistSubmit();
                    }}
                    placeholder="your@email.com"
                    className="flex-1 min-w-0 bg-white/5 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-white placeholder-white/30 outline-none focus:border-violet-500/50 transition"
                  />
                  <button
                    onClick={handleWaitlistSubmit}
                    disabled={!waitlistEmail.trim() || waitlistLoading}
                    className="shrink-0 px-3 py-1.5 rounded-xl text-xs font-medium text-white transition disabled:opacity-40"
                    style={{ background: "linear-gradient(135deg, #7c3aed, #6d28d9)" }}
                  >
                    {waitlistLoading ? "…" : "Notify Me"}
                  </button>
                </div>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Error ── */}
      {error && (
        <p className="text-center text-xs text-red-400 px-4 pb-1 shrink-0">{error}</p>
      )}

      {/* ── Activity toolbar (authenticated only) ── */}
      {!isGuest && (
        <div className="flex items-center gap-2 px-4 pb-1.5 shrink-0">
          <span className="text-white/20 text-[9px] uppercase tracking-widest mr-0.5">Play</span>
          {ACTIVITY_BUTTONS.map(({ type, icon, label }) => (
            <motion.button
              key={type}
              onClick={() => handleActivity(type)}
              disabled={isBusy || !!activityLoading}
              whileTap={{ scale: 0.94 }}
              title={label}
              className={`flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-full border transition disabled:opacity-40 ${accentColor}`}
              style={{ background: "rgba(255,255,255,0.03)" }}
            >
              {activityLoading === type ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <span className="text-xs">{icon}</span>
              )}
              <span className="hidden xs:inline">{label}</span>
            </motion.button>
          ))}
        </div>
      )}

      {/* ── Input row ── */}
      <div className="flex items-end gap-2 px-4 pb-4 shrink-0">
        <div className="flex-1">
          <TextInput
            onSend={(text) => { sendMessage(text); onMessageConsumed?.(); }}
            disabled={isBusy || showUpgradeCard}
            nsfw={persona.nsfw_mode}
            placeholder={inputPlaceholder}
            romantic={romanticMode}
            initialValue={initialMessage}
          />
        </div>

        {/* Selfie — authenticated only */}
        {!isGuest && (
          <motion.button
            onClick={handleSelfie}
            disabled={isBusy || selfieLoading}
            whileTap={{ scale: 0.93 }}
            title="Ask for a selfie 📸"
            className={`w-12 h-12 rounded-full border flex items-center justify-center transition disabled:opacity-40 disabled:cursor-not-allowed ${accentColor}`}
            style={{ background: "rgba(255,255,255,0.04)" }}
          >
            {selfieLoading
              ? <Loader2 className="w-5 h-5 animate-spin" />
              : <Camera className="w-5 h-5" />
            }
          </motion.button>
        )}

        <PushToTalkButton
          state={recorderState}
          onStart={start}
          onStop={stop}
          disabled={busy || showUpgradeCard}
          nsfw={persona.nsfw_mode}
          isPremium={isPremium}
        />
      </div>

      {/* ── Age Gate Modal ── */}
      <AnimatePresence>
        {showAgeGate && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center px-4"
            style={{ background: "rgba(0,0,0,0.7)", backdropFilter: "blur(8px)" }}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.94, y: 12 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.94, y: 8 }}
              className="relative w-full max-w-sm rounded-2xl overflow-hidden"
              style={{
                background: "linear-gradient(135deg, #1a0a1e, #1e0f2a)",
                border: "1px solid rgba(251,113,133,0.2)",
                boxShadow: "0 24px 60px rgba(0,0,0,0.6), 0 0 40px rgba(159,18,57,0.12)",
              }}
            >
              <div
                className="absolute top-0 inset-x-0 h-px"
                style={{ background: "linear-gradient(90deg, transparent, rgba(251,113,133,0.4), transparent)" }}
              />

              <div className="px-6 pt-7 pb-6">
                <div className="flex justify-center mb-4">
                  <div
                    className="w-12 h-12 rounded-full flex items-center justify-center"
                    style={{
                      background: "rgba(159,18,57,0.2)",
                      border: "1px solid rgba(251,113,133,0.3)",
                      boxShadow: "0 0 20px rgba(251,113,133,0.15)",
                    }}
                  >
                    <Moon className="w-5 h-5 text-rose-400" />
                  </div>
                </div>

                <h2 className="text-center text-lg font-semibold text-white mb-2">
                  Romantic Mode
                </h2>
                <p className="text-center text-sm text-white/55 leading-relaxed mb-7">
                  More intimate conversations for 18+ users. By continuing, you confirm you are at least 18 years of age.
                </p>

                <div className="flex gap-3">
                  <button
                    onClick={() => setShowAgeGate(false)}
                    className="flex-1 py-2.5 rounded-xl text-sm font-medium text-white/50 border border-white/10 hover:border-white/20 hover:text-white/70 transition"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleAgeGateConfirm}
                    className="flex-1 py-2.5 rounded-xl text-sm font-semibold text-white transition"
                    style={{
                      background: "linear-gradient(135deg, #9f1239, #be185d)",
                      boxShadow: "0 4px 16px rgba(159,18,57,0.4)",
                    }}
                  >
                    I'm 18+, Continue
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <QuotaModal
        detail={quotaErrorDetail}
        onClose={() => setQuotaErrorDetail(null)}
        onUpgrade={() => { setQuotaErrorDetail(null); onBack(); }}
      />
    </motion.div>
  );
}
