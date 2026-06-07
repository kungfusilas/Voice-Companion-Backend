import { useState, useCallback, useRef, useId, useEffect } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, Volume2, VolumeX, Camera, Loader2 } from "lucide-react";
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
} from "@/lib/api";
import { scoring } from "@/lib/scoring";
import type { Persona, ChatMessage, ActivityType } from "@/lib/api";

interface ChatPageProps {
  persona: Persona;
  relType: string;
  userId: string;
  onBack: () => void;
  onChangeRelType: () => void;
}

const ACTIVITY_BUTTONS: { type: ActivityType; icon: string; label: string }[] = [
  { type: "word_game",        icon: "🔤", label: "Word Game"        },
  { type: "trivia",           icon: "🧠", label: "Trivia"           },
  { type: "would_you_rather", icon: "🤔", label: "Would You Rather" },
];

export function ChatPage({ persona, relType, userId, onBack, onChangeRelType }: ChatPageProps) {
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

  const busyRef = useRef(false);
  const { playing: speaking, play: playAudio } = useAudioPlayer();

  // Init meter from DB
  useEffect(() => {
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
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [persona.id, relType, userId]);

  // Load proactive messages (including activity payloads)
  useEffect(() => {
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
  }, [persona.id, persona.name, userId]);

  const sendMessage = useCallback(async (userText: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setProactiveLabel(null);
    setScoreDelta(undefined);
    setMessages((prev) => [...prev, { role: "user", content: userText }]);
    setStreamingText("");

    let fullReply = "";
    try {
      for await (const event of chatStream(sessionId, persona.id, userText, userId)) {
        if (event.type === "token") {
          fullReply += event.text ?? "";
          setStreamingText(fullReply);
        } else if (event.type === "done") {
          fullReply = event.full_text ?? fullReply;
          setStreamingText("");
          const newMsgs: ChatMessage[] = [{ role: "assistant", content: fullReply }];
          if (event.stage_up_text) newMsgs.push({ role: "assistant", content: event.stage_up_text });
          setMessages((prev) => [...prev, ...newMsgs]);

          if (event.connection_score !== undefined) {
            setConnectionScore(event.connection_score);
            setScoreDelta(event.score_delta);
            setStageName(event.stage_name ?? "");
            setStageMin(event.stage_min ?? 0);
            setStageMax(event.stage_max ?? 100);
          }

          if (ttsEnabled && fullReply) {
            try { await playAudio(await speakText(fullReply, persona.id)); } catch {}
          }
        } else if (event.type === "error") {
          setError(event.message ?? "Unknown error");
          setStreamingText("");
        }
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Connection error");
      setStreamingText("");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [sessionId, persona.id, userId, ttsEnabled, playAudio]);

  const handleActivity = useCallback(async (type: ActivityType) => {
    if (activityLoading || busy) return;
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
  }, [persona.id, userId, activityLoading, busy]);

  const handleSelfie = useCallback(async () => {
    if (selfieLoading || busy) return;
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
  }, [persona.id, persona.name, userId, selfieLoading, busy]);

  const handleAudio = useCallback(async (blob: Blob) => {
    try {
      const transcript = await transcribeAudio(blob);
      if (transcript.trim()) await sendMessage(transcript);
    } catch {
      setError("Transcription failed — try again");
    } finally {
      resetRecorder();
    }
  }, [sendMessage]); // eslint-disable-line react-hooks/exhaustive-deps

  const { state: recorderState, start, stop, reset: resetRecorder } = useVoiceRecorder(handleAudio);
  const isBusy = busy || recorderState === "processing";

  const typeColors: Record<string, string> = {
    romance:      "border-rose-800/40 text-rose-400 hover:bg-rose-900/30",
    mentor:       "border-violet-800/40 text-violet-400 hover:bg-violet-900/30",
    friendship:   "border-teal-800/40 text-teal-400 hover:bg-teal-900/30",
    professional: "border-sky-800/40 text-sky-400 hover:bg-sky-900/30",
  };
  const accentColor = persona.nsfw_mode
    ? "border-red-800/40 text-red-400 hover:bg-red-900/30"
    : (typeColors[relType] ?? typeColors.romance);

  return (
    <motion.div
      initial={{ opacity: 0, x: 30 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -30 }}
      className="flex flex-col h-full"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 pt-4 pb-2 shrink-0">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-white/50 hover:text-white transition text-sm"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>
        <div className="flex items-center gap-2">
          <MemoriesPanel
            userId={userId}
            personaId={persona.id}
            personaName={persona.name}
            nsfw={persona.nsfw_mode}
          />
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

      {/* Avatar */}
      <div className="flex justify-center py-3 shrink-0">
        <Avatar
          name={persona.name}
          personaId={persona.id}
          speaking={speaking}
          listening={recorderState === "recording"}
          nsfw={persona.nsfw_mode}
        />
      </div>

      {/* Backend badge */}
      <div className="flex justify-center mb-2 shrink-0">
        <span
          className={`text-xs px-2.5 py-0.5 rounded-full border cursor-pointer ${
            persona.nsfw_mode
              ? "bg-red-950/40 border-red-800/40 text-red-400"
              : "bg-violet-950/40 border-violet-800/40 text-violet-400"
          }`}
          onClick={onChangeRelType}
          title="Change relationship type"
        >
          {persona.nsfw_mode ? "Venice.ai · uncensored" : "Claude · standard"}
        </span>
      </div>

      {/* Connection Meter */}
      {stageName && (
        <ConnectionMeter
          score={connectionScore}
          stageName={stageName}
          stageMin={stageMin}
          stageMax={stageMax}
          relType={relType}
          scoreDelta={scoreDelta}
        />
      )}

      {/* Proactive label */}
      {proactiveLabel && (
        <div className="flex justify-center px-4 mb-1 shrink-0">
          <span className="text-[11px] text-violet-300/60 italic bg-violet-950/30 border border-violet-800/20 px-3 py-1 rounded-full">
            {proactiveLabel}
          </span>
        </div>
      )}

      {/* Transcript */}
      <ChatTranscript
        messages={messages}
        streamingText={streamingText}
        personaName={persona.name}
        nsfw={persona.nsfw_mode}
        userId={userId}
        onChatContinue={sendMessage}
      />

      {/* Error */}
      {error && (
        <p className="text-center text-xs text-red-400 px-4 pb-1 shrink-0">{error}</p>
      )}

      {/* Activity toolbar */}
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

      {/* Input row */}
      <div className="flex items-end gap-2 px-4 pb-4 shrink-0">
        <div className="flex-1">
          <TextInput onSend={sendMessage} disabled={isBusy} nsfw={persona.nsfw_mode} />
        </div>

        {/* Selfie button */}
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

        <PushToTalkButton
          state={recorderState}
          onStart={start}
          onStop={stop}
          disabled={busy}
          nsfw={persona.nsfw_mode}
        />
      </div>
    </motion.div>
  );
}
