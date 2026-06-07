import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { ChatMessage } from "@/lib/api";

interface ChatTranscriptProps {
  messages: ChatMessage[];
  streamingText: string;
  personaName: string;
  nsfw: boolean;
}

export function ChatTranscript({ messages, streamingText, personaName, nsfw }: ChatTranscriptProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText]);

  const accentBg = nsfw ? "bg-red-900/30 border-red-800/40" : "bg-violet-900/30 border-violet-800/40";
  const accentText = nsfw ? "text-red-200" : "text-violet-200";

  return (
    <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 scrollbar-thin scrollbar-thumb-white/10">
      <AnimatePresence initial={false}>
        {messages.map((msg, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2 }}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            {msg.imageUrl ? (
              /* ── Selfie / image message ── */
              <div className={`max-w-[72%] rounded-2xl rounded-bl-sm overflow-hidden border ${accentBg}`}>
                <div className={`px-3 pt-2.5 pb-1 text-xs font-medium opacity-60 ${accentText}`}>
                  {personaName}
                </div>
                <img
                  src={msg.imageUrl}
                  alt={`${personaName} selfie`}
                  className="w-full max-w-[250px] block"
                  style={{ maxHeight: 250, objectFit: "cover" }}
                />
                <p className={`px-3 py-2 text-xs ${accentText} opacity-70`}>
                  {msg.content}
                </p>
              </div>
            ) : (
              /* ── Regular text message ── */
              <div
                className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed border ${
                  msg.role === "user"
                    ? "bg-white/10 border-white/10 text-white/90 rounded-br-sm"
                    : `${accentBg} ${accentText} rounded-bl-sm`
                }`}
              >
                {msg.role === "assistant" && (
                  <span className="text-xs font-medium opacity-60 block mb-1">{personaName}</span>
                )}
                {msg.content}
              </div>
            )}
          </motion.div>
        ))}

        {streamingText && (
          <motion.div
            key="streaming"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex justify-start"
          >
            <div className={`max-w-[80%] rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm leading-relaxed border ${accentBg} ${accentText}`}>
              <span className="text-xs font-medium opacity-60 block mb-1">{personaName}</span>
              {streamingText}
              <motion.span
                className="inline-block w-1.5 h-3.5 ml-0.5 rounded-sm bg-current align-middle"
                animate={{ opacity: [1, 0, 1] }}
                transition={{ duration: 0.8, repeat: Infinity }}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <div ref={bottomRef} />
    </div>
  );
}
