import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Brain, X, RefreshCw } from "lucide-react";
import { fetchMemories } from "@/lib/api";
import type { Memory } from "@/lib/api";

interface MemoriesPanelProps {
  userId: string;
  personaId: string;
  personaName: string;
  nsfw: boolean;
}

export function MemoriesPanel({ userId, personaId, personaName, nsfw }: MemoriesPanelProps) {
  const [open, setOpen] = useState(false);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const accent = nsfw ? "red" : "violet";

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchMemories(userId, personaId);
      setMemories(data.memories);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load memories");
    } finally {
      setLoading(false);
    }
  }, [userId, personaId]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const ringCls = nsfw
    ? "border-red-700/40 bg-red-950/30 text-red-400 hover:bg-red-900/30"
    : "border-violet-700/40 bg-violet-950/30 text-violet-400 hover:bg-violet-900/30";

  const headerCls = nsfw ? "text-red-400" : "text-violet-400";

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="What I remember"
        className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border transition ${ringCls}`}
      >
        <Brain className="w-3.5 h-3.5" />
        Memory
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-end justify-center p-4 bg-black/60 backdrop-blur-sm"
            onClick={(e) => e.target === e.currentTarget && setOpen(false)}
          >
            <motion.div
              initial={{ y: 80, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: 80, opacity: 0 }}
              transition={{ type: "spring", damping: 24, stiffness: 260 }}
              className="w-full max-w-md bg-[#0f0f1a] border border-white/10 rounded-2xl overflow-hidden shadow-2xl"
            >
              {/* Header */}
              <div className="flex items-center justify-between px-5 py-4 border-b border-white/10">
                <div className="flex items-center gap-2">
                  <Brain className={`w-4 h-4 ${headerCls}`} />
                  <span className="text-sm font-semibold text-white/90">
                    What {personaName} remembers
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={load}
                    disabled={loading}
                    className="p-1.5 rounded-full text-white/40 hover:text-white/70 hover:bg-white/5 transition"
                    title="Refresh"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
                  </button>
                  <button
                    onClick={() => setOpen(false)}
                    className="p-1.5 rounded-full text-white/40 hover:text-white/70 hover:bg-white/5 transition"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Body */}
              <div className="px-5 py-4 max-h-[60vh] overflow-y-auto space-y-2">
                {loading && (
                  <div className="flex justify-center py-8">
                    <div className={`w-5 h-5 border-2 border-t-transparent rounded-full animate-spin ${
                      nsfw ? "border-red-500" : "border-violet-500"
                    }`} />
                  </div>
                )}

                {!loading && error && (
                  <p className="text-center text-xs text-red-400 py-6">{error}</p>
                )}

                {!loading && !error && memories.length === 0 && (
                  <div className="text-center py-8">
                    <Brain className="w-8 h-8 mx-auto mb-3 text-white/15" />
                    <p className="text-sm text-white/40">No memories yet</p>
                    <p className="text-xs text-white/25 mt-1">
                      Facts will appear here as you chat
                    </p>
                  </div>
                )}

                {!loading && memories.map((m) => (
                  <motion.div
                    key={m.id}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="flex items-start gap-3 py-2 px-3 rounded-xl bg-white/[0.03] border border-white/[0.06]"
                  >
                    <span className={`mt-0.5 shrink-0 w-1.5 h-1.5 rounded-full ${
                      nsfw ? "bg-red-500" : "bg-violet-500"
                    }`} />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-white/80 leading-relaxed">{m.content}</p>
                      <p className="text-xs text-white/25 mt-0.5">
                        {new Date(m.created_at).toLocaleDateString(undefined, {
                          month: "short", day: "numeric", year: "numeric",
                        })}
                      </p>
                    </div>
                  </motion.div>
                ))}
              </div>

              {!loading && memories.length > 0 && (
                <div className="px-5 py-3 border-t border-white/10">
                  <p className="text-xs text-white/30 text-center">
                    {memories.length} {memories.length === 1 ? "memory" : "memories"} stored
                  </p>
                </div>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
