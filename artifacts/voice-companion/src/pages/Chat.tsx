import { useState, useCallback, useRef, useId, useEffect } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, Volume2, VolumeX, Camera, Loader2 } from "lucide-react";
import { Avatar } from "@/components/Avatar";
import { ChatTranscript } from "@/components/ChatTranscript";
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
} from "@/lib/api";
import type { Persona, ChatMessage } from "@/lib/api";

interface ChatPageProps {
  persona: Persona;
  onBack: () => void;
}

// Stable user_id scoped to this browser session
const USER_ID = (() => {
  const key = "vc_user_id";
  let id = localStorage.getItem(key);
  if (!id) {
    id = `u_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
    localStorage.setItem(key, id);
  }
  return id;
})();

export function ChatPage({ persona, onBack }: ChatPageProps) {
  const rawId = useId();
  const sessionId = rawId.replace(/:/g, "s");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [selfieLoading, setSelfieLoading] = useState(false);
  const [error, setError] = useState("");
  const [proactiveLabel, setProactiveLabel] = useState<string | null>(null);
  const busyRef = useRef(false);

  const { playing: speaking, play: playAudio } = useAudioPlayer();

  // On mount: load any pending proactive messages and prepend them
  useEffect(() => {
    let cancelled = false;
    async function loadProactive() {
      try {
        const data = await fetchProactiveMessages(USER_ID, persona.id);
        if (cancelled || !data.messages.length) return;
        const proactiveMessages: ChatMessage[] = data.messages.map((m) => ({
          role: "assistant",
          content: m.message,
          proactive: true,
        }));
        setMessages(proactiveMessages);
        setProactiveLabel(`💭 ${persona.name} was thinking about you while you were away`);
      } catch {
        // non-fatal
      }
    }
    loadProactive();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [persona.id]);

  const sendMessage = useCallback(async (userText: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setProactiveLabel(null);
    setMessages((prev) => [...prev, { role: "user", content: userText }]);
    setStreamingText("");

    let fullReply = "";
    try {
      for await (const event of chatStream(sessionId, persona.id, userText)) {
        if (event.type === "token") {
          fullReply += event.text ?? "";
          setStreamingText(fullReply);
        } else if (event.type === "done") {
          fullReply = event.full_text ?? fullReply;
          setStreamingText("");
          setMessages((prev) => [...prev, { role: "assistant", content: fullReply }]);
          if (ttsEnabled && fullReply) {
            try {
              const blob = await speakText(fullReply, persona.id);
              await playAudio(blob);
            } catch {
              // TTS failure is non-fatal
            }
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
  }, [sessionId, persona.id, ttsEnabled, playAudio]);

  const handleSelfie = useCallback(async () => {
    if (selfieLoading || busy) return;
    setSelfieLoading(true);
    setError("");
    try {
      const imageUrl = await requestSelfie(persona.id, USER_ID);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `${persona.name} sent you a photo 📸`,
          imageUrl,
        },
      ]);
    } catch {
      setError("Couldn't generate selfie — try again");
    } finally {
      setSelfieLoading(false);
    }
  }, [persona.id, persona.name, selfieLoading, busy]);

  const handleAudio = useCallback(async (blob: Blob) => {
    try {
      const transcript = await transcribeAudio(blob);
      if (transcript.trim()) {
        await sendMessage(transcript);
      }
    } catch {
      setError("Transcription failed — try again");
    } finally {
      resetRecorder();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sendMessage]);

  const { state: recorderState, start, stop, reset: resetRecorder } = useVoiceRecorder(handleAudio);

  const isBusy = busy || recorderState === "processing";

  const cameraColor = persona.nsfw_mode
    ? "border-red-800/40 text-red-400 hover:bg-red-900/30"
    : "border-violet-800/40 text-violet-400 hover:bg-violet-900/30";

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
            userId={USER_ID}
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
      <div className="flex justify-center py-4 shrink-0">
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
          className={`text-xs px-2.5 py-0.5 rounded-full border ${
            persona.nsfw_mode
              ? "bg-red-950/40 border-red-800/40 text-red-400"
              : "bg-violet-950/40 border-violet-800/40 text-violet-400"
          }`}
        >
          {persona.nsfw_mode ? "Venice.ai · uncensored" : "Claude · standard"}
        </span>
      </div>

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
      />

      {/* Error */}
      {error && (
        <p className="text-center text-xs text-red-400 px-4 pb-1 shrink-0">{error}</p>
      )}

      {/* Controls */}
      <div className="flex items-end gap-2 px-4 pb-4 shrink-0">
        <div className="flex-1">
          <TextInput onSend={sendMessage} disabled={isBusy} nsfw={persona.nsfw_mode} />
        </div>

        {/* Camera / selfie button */}
        <motion.button
          onClick={handleSelfie}
          disabled={isBusy || selfieLoading}
          whileTap={{ scale: 0.93 }}
          title="Ask for a selfie 📸"
          className={`w-12 h-12 rounded-full border flex items-center justify-center transition disabled:opacity-40 disabled:cursor-not-allowed ${cameraColor}`}
          style={{ background: "rgba(255,255,255,0.04)" }}
        >
          {selfieLoading ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <Camera className="w-5 h-5" />
          )}
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
