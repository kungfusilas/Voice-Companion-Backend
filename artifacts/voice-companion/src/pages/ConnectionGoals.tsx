import { useEffect, useState, useRef } from "react";
import { Target, Plus, Trash2, CheckCircle2 } from "lucide-react";
import { apiFetchJSON, apiFetch } from "@/lib/api";

interface Goal {
  id: string;
  goal: string;
  created_at: string;
}

const SUGGESTIONS = [
  "Be more present with family",
  "Improve communication with my partner",
  "Listen more, talk less",
  "Show appreciation daily",
  "Resolve conflicts calmly",
  "Build deeper friendships",
];

interface Props {
  userId: string;
}

export function ConnectionGoals({ userId }: Props) {
  const [goals, setGoals]       = useState<Goal[]>([]);
  const [loading, setLoading]   = useState(true);
  const [saving, setSaving]     = useState(false);
  const [input, setInput]       = useState("");
  const [error, setError]       = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const fetchGoals = async () => {
    try {
      const data = await apiFetchJSON<{ goals: Goal[] }>("/companion/api/goals");
      setGoals(data.goals ?? []);
    } catch {
      setError("Could not load goals.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchGoals(); }, [userId]);

  const addGoal = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || saving) return;
    setSaving(true);
    setError(null);
    try {
      const newGoal = await apiFetchJSON<Goal>("/companion/api/goals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal: trimmed }),
      });
      setGoals((prev) => [...prev, newGoal]);
      setInput("");
    } catch {
      setError("Could not save goal.");
    } finally {
      setSaving(false);
    }
  };

  const deleteGoal = async (id: string) => {
    setGoals((prev) => prev.filter((g) => g.id !== id));
    try {
      await apiFetch(`/companion/api/goals/${id}`, { method: "DELETE" });
    } catch {
      fetchGoals();
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-5 pt-2">
      <div className="flex items-center gap-2">
        <Target className="w-4 h-4 text-violet-400" />
        <p className="text-white/50 text-xs">Set personal relationship goals to work toward</p>
      </div>

      {/* Input */}
      <div
        className="rounded-2xl p-4"
        style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
      >
        <p className="text-white/50 text-xs mb-2.5 font-medium">Add a new goal</p>
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addGoal(input)}
            placeholder="e.g. Be more present with family"
            className="flex-1 px-3 py-2 rounded-xl bg-white/05 border border-white/10 text-white placeholder-white/25 text-xs focus:outline-none focus:border-violet-500/50 transition-colors"
          />
          <button
            onClick={() => addGoal(input)}
            disabled={!input.trim() || saving}
            className="px-3 py-2 rounded-xl bg-violet-600/40 hover:bg-violet-600/60 disabled:opacity-40 text-white border border-violet-500/30 transition-all"
          >
            {saving ? (
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <Plus className="w-4 h-4" />
            )}
          </button>
        </div>

        {/* Quick suggestions */}
        <div className="flex flex-wrap gap-1.5 mt-3">
          {SUGGESTIONS.filter((s) => !goals.find((g) => g.goal === s)).slice(0, 4).map((s) => (
            <button
              key={s}
              onClick={() => addGoal(s)}
              className="text-[10px] px-2.5 py-1 rounded-full text-white/40 hover:text-white/70 transition-colors"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
            >
              + {s}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-red-400/70 text-xs text-center">{error}</p>}

      {/* Goals list */}
      {goals.length === 0 ? (
        <div className="text-center py-10">
          <CheckCircle2 className="w-8 h-8 text-white/15 mx-auto mb-3" />
          <p className="text-white/30 text-sm">No goals yet.</p>
          <p className="text-white/20 text-xs mt-1">Add your first relationship goal above.</p>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-white/35 text-[10px] uppercase tracking-wider font-medium">Your Goals</p>
          {goals.map((g) => (
            <div
              key={g.id}
              className="flex items-start gap-3 rounded-xl px-3.5 py-3"
              style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
            >
              <CheckCircle2 className="w-4 h-4 text-violet-400/60 mt-0.5 shrink-0" />
              <p className="flex-1 text-white/75 text-xs leading-relaxed">{g.goal}</p>
              <button
                onClick={() => deleteGoal(g.id)}
                className="text-white/20 hover:text-red-400/70 transition-colors mt-0.5 shrink-0"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
