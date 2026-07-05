import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Lock, Eye, EyeOff, Trash2, Pencil, Check, X, Loader2, Unlock, RefreshCw } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { Persona } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface MemoryRow {
  id: string;
  content: string;
  memory_type: string;
  importance: number;
  category: string;
  locked: boolean;
  sensitive: boolean;
  created_at: string;
}

interface GroupedMemories {
  [category: string]: MemoryRow[];
}

// ── Category meta ─────────────────────────────────────────────────────────────

const CATEGORY_META: Record<string, { icon: string; label: string; color: string }> = {
  people:        { icon: "👥", label: "People",       color: "text-sky-400"    },
  goals:         { icon: "🎯", label: "Goals",        color: "text-amber-400"  },
  milestones:    { icon: "🏆", label: "Milestones",   color: "text-violet-400" },
  preferences:   { icon: "⭐", label: "Preferences",  color: "text-yellow-400" },
  wounds:        { icon: "💔", label: "Wounds",       color: "text-rose-400"   },
  wins:          { icon: "🎉", label: "Wins",         color: "text-emerald-400"},
  dreams:        { icon: "💭", label: "Dreams",       color: "text-indigo-400" },
  reminders:     { icon: "🔔", label: "Reminders",    color: "text-orange-400" },
  uncategorized: { icon: "📝", label: "Other",        color: "text-white/40"   },
};

const CATEGORY_ORDER = ["people","goals","milestones","wins","dreams","preferences","reminders","wounds","uncategorized"];

const BASE = "/companion/api";

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchDashboard(companionId: string): Promise<GroupedMemories> {
  const resp = await apiFetch(`${BASE}/memory-dashboard?companion_id=${encodeURIComponent(companionId)}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = await resp.json();
  return data.groups as GroupedMemories;
}

async function patchMemory(
  memoryId: string,
  companionId: string,
  update: { text?: string; locked?: boolean; sensitive?: boolean },
): Promise<MemoryRow> {
  const resp = await apiFetch(`${BASE}/memory-dashboard/${encodeURIComponent(memoryId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ companion_id: companionId, ...update }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body?.detail?.message ?? `HTTP ${resp.status}`);
  }
  const data = await resp.json();
  return data.memory as MemoryRow;
}

async function deleteMemory(memoryId: string, companionId: string): Promise<void> {
  const resp = await apiFetch(
    `${BASE}/memory-dashboard/${encodeURIComponent(memoryId)}?companion_id=${encodeURIComponent(companionId)}`,
    { method: "DELETE" },
  );
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body?.detail?.message ?? `HTTP ${resp.status}`);
  }
}

async function triggerBackfill(companionId: string): Promise<{ classified: number }> {
  const resp = await apiFetch(
    `${BASE}/memory-dashboard/backfill?companion_id=${encodeURIComponent(companionId)}`,
    { method: "POST" },
  );
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

// ── Memory card ───────────────────────────────────────────────────────────────

interface MemoryCardProps {
  memory: MemoryRow;
  companionId: string;
  onUpdated: (updated: MemoryRow) => void;
  onDeleted: (id: string) => void;
}

function MemoryCard({ memory: m, companionId, onUpdated, onDeleted }: MemoryCardProps) {
  const [revealed, setRevealed]     = useState(false);
  const [editing, setEditing]       = useState(false);
  const [editText, setEditText]     = useState(m.content);
  const [saving, setSaving]         = useState(false);
  const [toggling, setToggling]     = useState<"lock" | "sensitive" | null>(null);
  const [deleting, setDeleting]     = useState(false);
  const [error, setError]           = useState("");

  const handleSaveEdit = useCallback(async () => {
    if (!editText.trim() || editText === m.content) { setEditing(false); return; }
    setSaving(true); setError("");
    try {
      const updated = await patchMemory(m.id, companionId, { text: editText.trim() });
      onUpdated(updated);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally { setSaving(false); }
  }, [editText, m.id, m.content, companionId, onUpdated]);

  const handleToggleLock = useCallback(async () => {
    setToggling("lock"); setError("");
    try {
      const updated = await patchMemory(m.id, companionId, { locked: !m.locked });
      onUpdated(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally { setToggling(null); }
  }, [m.id, m.locked, companionId, onUpdated]);

  const handleToggleSensitive = useCallback(async () => {
    setToggling("sensitive"); setError("");
    try {
      const updated = await patchMemory(m.id, companionId, { sensitive: !m.sensitive });
      onUpdated(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally { setToggling(null); }
  }, [m.id, m.sensitive, companionId, onUpdated]);

  const handleDelete = useCallback(async () => {
    if (m.locked) return;
    setDeleting(true); setError("");
    try {
      await deleteMemory(m.id, companionId);
      onDeleted(m.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
      setDeleting(false);
    }
  }, [m.id, m.locked, companionId, onDeleted]);

  return (
    <div
      className="rounded-xl border px-3 py-2.5 space-y-2 transition"
      style={{
        background: "rgba(255,255,255,0.03)",
        borderColor: m.locked ? "rgba(251,191,36,0.2)" : "rgba(255,255,255,0.07)",
      }}
    >
      {/* Content area */}
      {editing ? (
        <div className="space-y-1.5">
          <textarea
            className="w-full text-xs text-white/80 bg-white/05 border border-white/15 rounded-lg px-2.5 py-2 resize-none focus:outline-none focus:border-violet-500/50"
            rows={3}
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            autoFocus
          />
          <div className="flex gap-1.5">
            <button
              onClick={handleSaveEdit}
              disabled={saving}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-medium bg-violet-600/40 text-violet-200 hover:bg-violet-600/60 transition disabled:opacity-50"
            >
              {saving ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <Check className="w-2.5 h-2.5" />}
              Save
            </button>
            <button
              onClick={() => { setEditing(false); setEditText(m.content); }}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] text-white/40 hover:text-white/60 transition"
            >
              <X className="w-2.5 h-2.5" /> Cancel
            </button>
          </div>
        </div>
      ) : (
        <div
          className={`text-xs leading-relaxed transition-all ${
            m.sensitive && !revealed
              ? "blur-sm select-none cursor-pointer"
              : "text-white/75"
          }`}
          onClick={() => m.sensitive && !revealed && setRevealed(true)}
          title={m.sensitive && !revealed ? "Tap to reveal" : undefined}
        >
          {m.content}
          {m.sensitive && !revealed && (
            <span className="block text-[10px] text-white/30 mt-0.5 blur-none not-italic">
              tap to reveal
            </span>
          )}
        </div>
      )}

      {error && (
        <p className="text-[10px] text-rose-400">{error}</p>
      )}

      {/* Controls */}
      <div className="flex items-center justify-between pt-0.5">
        {/* Badges */}
        <div className="flex items-center gap-1.5">
          {m.locked && (
            <span className="flex items-center gap-0.5 text-[9px] text-amber-400/70 bg-amber-400/08 border border-amber-400/15 px-1.5 py-0.5 rounded-full">
              <Lock className="w-2 h-2" /> Locked
            </span>
          )}
          {m.sensitive && revealed && (
            <span className="flex items-center gap-0.5 text-[9px] text-rose-400/70 bg-rose-400/08 border border-rose-400/15 px-1.5 py-0.5 rounded-full">
              <EyeOff className="w-2 h-2" /> Sensitive
            </span>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-0.5">
          {/* Edit */}
          {!editing && (
            <button
              onClick={() => { setEditing(true); setEditText(m.content); setRevealed(true); }}
              title="Edit"
              className="p-1.5 rounded-lg text-white/25 hover:text-white/60 hover:bg-white/05 transition"
            >
              <Pencil className="w-3 h-3" />
            </button>
          )}

          {/* Lock toggle */}
          <button
            onClick={handleToggleLock}
            disabled={toggling === "lock"}
            title={m.locked ? "Unlock" : "Lock"}
            className="p-1.5 rounded-lg transition hover:bg-white/05 disabled:opacity-40"
            style={{ color: m.locked ? "rgba(251,191,36,0.7)" : "rgba(255,255,255,0.25)" }}
          >
            {toggling === "lock"
              ? <Loader2 className="w-3 h-3 animate-spin" />
              : m.locked ? <Lock className="w-3 h-3" /> : <Unlock className="w-3 h-3" />
            }
          </button>

          {/* Sensitive toggle */}
          <button
            onClick={handleToggleSensitive}
            disabled={toggling === "sensitive"}
            title={m.sensitive ? "Mark not sensitive" : "Mark sensitive"}
            className="p-1.5 rounded-lg transition hover:bg-white/05 disabled:opacity-40"
            style={{ color: m.sensitive ? "rgba(251,113,133,0.7)" : "rgba(255,255,255,0.25)" }}
          >
            {toggling === "sensitive"
              ? <Loader2 className="w-3 h-3 animate-spin" />
              : m.sensitive ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />
            }
          </button>

          {/* Delete */}
          <button
            onClick={handleDelete}
            disabled={m.locked || deleting}
            title={m.locked ? "Unlock to delete" : "Delete"}
            className="p-1.5 rounded-lg transition hover:bg-white/05 disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ color: m.locked ? "rgba(255,255,255,0.15)" : "rgba(251,113,133,0.5)" }}
          >
            {deleting
              ? <Loader2 className="w-3 h-3 animate-spin" />
              : <Trash2 className="w-3 h-3" />
            }
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Upgrade prompt ────────────────────────────────────────────────────────────

function UpgradePrompt({ onUpgrade }: { onUpgrade?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center space-y-4">
      <div className="text-4xl">🧠</div>
      <h2 className="text-white font-semibold text-base">Memory Dashboard</h2>
      <p className="text-white/40 text-sm leading-relaxed max-w-xs">
        View, edit, lock, and mark memories sensitive. Auto-categorized by AI.
        Available on Premium and above.
      </p>
      {onUpgrade && (
        <button
          onClick={onUpgrade}
          className="mt-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition"
          style={{ background: "linear-gradient(135deg, #7c3aed, #6d28d9)", boxShadow: "0 4px 14px rgba(124,58,237,0.4)" }}
        >
          Upgrade to Premium
        </button>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface MemoryDashboardProps {
  currentPersona: Persona | null;
  isPremium: boolean;
  onUpgrade?: () => void;
}

export function MemoryDashboard({ currentPersona, isPremium, onUpgrade }: MemoryDashboardProps) {
  const [groups, setGroups] = useState<GroupedMemories>({});
  const [loading, setLoading] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillMsg, setBackfillMsg] = useState("");
  const [fetchError, setFetchError] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>("people");

  const companionId = currentPersona?.id ?? "";

  const load = useCallback(async () => {
    if (!companionId || !isPremium) return;
    setLoading(true); setFetchError("");
    try {
      const g = await fetchDashboard(companionId);
      setGroups(g);
      // Auto-select first non-empty category
      const first = CATEGORY_ORDER.find((c) => (g[c]?.length ?? 0) > 0);
      if (first) setActiveCategory(first);
    } catch (e) {
      setFetchError(e instanceof Error ? e.message : "Failed to load memories");
    } finally { setLoading(false); }
  }, [companionId, isPremium]);

  useEffect(() => { load(); }, [load]);

  const handleUpdated = useCallback((updated: MemoryRow) => {
    setGroups((prev) => {
      const next = { ...prev };
      for (const cat of Object.keys(next)) {
        next[cat] = next[cat].map((m) => m.id === updated.id ? updated : m);
      }
      return next;
    });
  }, []);

  const handleDeleted = useCallback((id: string) => {
    setGroups((prev) => {
      const next = { ...prev };
      for (const cat of Object.keys(next)) {
        next[cat] = next[cat].filter((m) => m.id !== id);
      }
      return next;
    });
  }, []);

  const handleBackfill = useCallback(async () => {
    if (!companionId) return;
    setBackfilling(true); setBackfillMsg("");
    try {
      const res = await triggerBackfill(companionId);
      setBackfillMsg(`Categorized ${res.classified} memories`);
      await load();
    } catch {
      setBackfillMsg("Backfill failed");
    } finally { setBackfilling(false); }
  }, [companionId, load]);

  if (!isPremium) {
    return <UpgradePrompt onUpgrade={onUpgrade} />;
  }

  if (!currentPersona) {
    return (
      <div className="py-16 text-center text-white/30 text-sm">
        Select a companion first to view memories.
      </div>
    );
  }

  const activeMemories = groups[activeCategory] ?? [];
  const totalCount = CATEGORY_ORDER.reduce((s, c) => s + (groups[c]?.length ?? 0), 0);
  const uncatCount = groups["uncategorized"]?.length ?? 0;

  return (
    <div className="space-y-4 pt-2">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-white font-semibold text-sm">Memory Dashboard</h2>
          <p className="text-white/30 text-[11px] mt-0.5">{totalCount} memories with {currentPersona.name}</p>
        </div>
        <div className="flex items-center gap-2">
          {uncatCount > 0 && (
            <button
              onClick={handleBackfill}
              disabled={backfilling}
              title={`Categorize ${uncatCount} uncategorized memories`}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-[11px] text-white/50 border border-white/10 hover:text-white/70 hover:bg-white/05 transition disabled:opacity-40"
            >
              {backfilling ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
              Auto-sort {uncatCount}
            </button>
          )}
          <button
            onClick={load}
            disabled={loading}
            className="p-1.5 rounded-xl text-white/30 hover:text-white/60 hover:bg-white/05 transition disabled:opacity-40"
          >
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {backfillMsg && (
        <p className="text-[11px] text-emerald-400/70">{backfillMsg}</p>
      )}

      {fetchError && (
        <p className="text-[11px] text-rose-400">{fetchError}</p>
      )}

      {/* Category tab bar */}
      <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-none">
        {CATEGORY_ORDER.map((cat) => {
          const meta = CATEGORY_META[cat];
          const count = groups[cat]?.length ?? 0;
          if (count === 0) return null;
          return (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-[11px] font-medium whitespace-nowrap shrink-0 border transition ${
                activeCategory === cat
                  ? "bg-white/08 border-white/15 text-white"
                  : "border-transparent text-white/40 hover:text-white/60"
              }`}
            >
              <span>{meta.icon}</span>
              <span>{meta.label}</span>
              <span className="text-[9px] opacity-50">{count}</span>
            </button>
          );
        })}
      </div>

      {/* Memory list */}
      {loading ? (
        <div className="flex justify-center py-10">
          <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <AnimatePresence mode="wait">
          <motion.div
            key={activeCategory}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="space-y-2"
          >
            {activeMemories.length === 0 ? (
              <p className="text-white/25 text-xs text-center py-8">
                No {CATEGORY_META[activeCategory]?.label.toLowerCase()} memories yet.
              </p>
            ) : (
              activeMemories.map((m) => (
                <MemoryCard
                  key={m.id}
                  memory={m}
                  companionId={companionId}
                  onUpdated={handleUpdated}
                  onDeleted={handleDeleted}
                />
              ))
            )}
          </motion.div>
        </AnimatePresence>
      )}
    </div>
  );
}
