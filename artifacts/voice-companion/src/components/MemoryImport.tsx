import { useState } from "react";
import { Upload, CheckCircle, AlertCircle } from "lucide-react";
import { motion } from "framer-motion";

interface MemoryImportProps {
  userId: string;
}

export function MemoryImport({ userId }: MemoryImportProps) {
  const [text, setText] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [result, setResult] = useState<{ imported: number; categories: string[] } | null>(null);
  const [error, setError] = useState("");

  async function handleSubmit() {
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
      setResult(data);
      setStatus("success");
      setText("");
    } catch (e: any) {
      setError(e.message || "Something went wrong");
      setStatus("error");
    }
  }

  return (
    <div className="bg-white/5 border border-white/10 rounded-2xl p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Upload className="w-4 h-4 text-purple-400" />
        <h3 className="text-sm font-semibold text-white">Import Memories</h3>
      </div>
      <p className="text-xs text-white/50">
        Paste journal entries, life details, or personal notes. Your companion learns from them.
      </p>
      {status === "success" && result ? (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-start gap-3 bg-green-500/10 border border-green-500/20 rounded-xl p-4"
        >
          <CheckCircle className="w-4 h-4 text-green-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm text-green-300 font-medium">{result.imported} memories imported</p>
            <p className="text-xs text-white/40 mt-0.5">Topics: {result.categories.join(", ")}</p>
            <button onClick={() => setStatus("idle")} className="text-xs text-purple-400 hover:text-purple-300 mt-2">
              Import more
            </button>
          </div>
        </motion.div>
      ) : (
        <>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste your journal, life story, or any personal details here..."
            className="w-full h-36 bg-white/5 border border-white/10 rounded-xl p-3 text-sm text-white placeholder:text-white/25 resize-none focus:outline-none focus:border-purple-500/50"
            disabled={status === "loading"}
          />
          {status === "error" && (
            <div className="flex items-center gap-2 text-xs text-red-400">
              <AlertCircle className="w-3.5 h-3.5" />
              {error}
            </div>
          )}
          <button
            onClick={handleSubmit}
            disabled={!text.trim() || status === "loading"}
            className="w-full py-2.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-xl transition-colors flex items-center justify-center gap-2"
          >
            {status === "loading" ? "Extracting memories..." : "Import to companion memory"}
          </button>
        </>
      )}
    </div>
  );
}
