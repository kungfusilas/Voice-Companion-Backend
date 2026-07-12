import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { BookOpen, PenLine, ChevronRight, Loader, CheckCircle } from "lucide-react";

interface OnboardingFlowProps {
  userId: string;
  companionName: string;
  onComplete: () => void;
}

type Tab = "write" | "journal";
type Status = "idle" | "loading" | "success" | "error";

export function OnboardingFlow({ userId, companionName, onComplete }: OnboardingFlowProps) {
  const [tab, setTab] = useState<Tab>("write");
  const [text, setText] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [importedCount, setImportedCount] = useState(0);
  const [error, setError] = useState("");

  const placeholder =
    tab === "write"
      ? 'E.g. "I am a 34-year-old teacher in Austin. My dad passed away last year and I have been processing that a lot lately. I love hiking, cooking Korean food, and I am trying to get better at setting boundaries..."'
      : "Paste journal entries, diary notes, or exported conversations here...";

  async function handleImport() {
    if (!text.trim() || status === "loading") return;
    setStatus("loading");
    setError("");
    try {
      const res = await fetch("/companion/api/import-memories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, user_id: userId }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Import failed");
      }
      const data = await res.json();
      setImportedCount(data.imported);
      setStatus("success");
      localStorage.setItem("onboarding_done_" + userId, "1");
    } catch (e: any) {
      setError(e.message || "Something went wrong");
      setStatus("error");
    }
  }

  function handleSkip() {
    localStorage.setItem("onboarding_done_" + userId, "1");
    onComplete();
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#0a0a0f] to-[#12001a] flex items-center justify-center px-4">
      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-lg"
      >
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-full bg-purple-600/20 border border-purple-500/30 flex items-center justify-center mx-auto mb-4 text-2xl">
            ✨
          </div>
          <h1 className="text-2xl font-bold text-white mb-2">
            Help {companionName} get to know you
          </h1>
          <p className="text-white/50 text-sm leading-relaxed">
            The more you share, the more personal your conversations become.
            You can always add more in settings later.
          </p>
        </div>

        <AnimatePresence mode="wait">
          {status === "success" ? (
            <motion.div
              key="success"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="text-center space-y-4"
            >
              <div className="bg-green-500/10 border border-green-500/20 rounded-2xl p-6">
                <CheckCircle className="w-10 h-10 text-green-400 mx-auto mb-3" />
                <p className="text-green-300 font-semibold text-lg">
                  {importedCount} memories added
                </p>
                <p className="text-white/40 text-sm mt-1">
                  {companionName} will weave these into your conversations naturally.
                </p>
              </div>
              <button
                onClick={onComplete}
                className="w-full py-3 bg-purple-600 hover:bg-purple-500 text-white font-semibold rounded-xl transition-colors flex items-center justify-center gap-2"
              >
                Start chatting <ChevronRight className="w-4 h-4" />
              </button>
            </motion.div>
          ) : (
            <motion.div key="form" className="space-y-4">
              <div className="flex bg-white/5 rounded-xl p-1 gap-1">
                <button
                  onClick={() => setTab("write")}
                  className={"flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-all " + (tab === "write" ? "bg-purple-600 text-white" : "text-white/40 hover:text-white/70")}
                >
                  <PenLine className="w-4 h-4" />
                  Tell me about yourself
                </button>
                <button
                  onClick={() => setTab("journal")}
                  className={"flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-all " + (tab === "journal" ? "bg-purple-600 text-white" : "text-white/40 hover:text-white/70")}
                >
                  <BookOpen className="w-4 h-4" />
                  Paste a journal
                </button>
              </div>

              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={placeholder}
                className="w-full h-44 bg-white/5 border border-white/10 rounded-xl p-4 text-sm text-white placeholder:text-white/20 resize-none focus:outline-none focus:border-purple-500/50 leading-relaxed"
                disabled={status === "loading"}
              />

              {status === "error" && (
                <p className="text-xs text-red-400">{error}</p>
              )}

              <button
                onClick={handleImport}
                disabled={!text.trim() || status === "loading"}
                className="w-full py-3 bg-purple-600 hover:bg-purple-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold rounded-xl transition-colors flex items-center justify-center gap-2"
              >
                {status === "loading" ? (
                  <>
                    <Loader className="w-4 h-4 animate-spin" />
                    Reading your story...
                  </>
                ) : (
                  <>
                    Let's go <ChevronRight className="w-4 h-4" />
                  </>
                )}
              </button>

              <button
                onClick={handleSkip}
                className="w-full py-2 text-white/30 hover:text-white/50 text-sm transition-colors"
              >
                Skip for now
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
