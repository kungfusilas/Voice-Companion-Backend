import { useState, useEffect, useCallback } from "react";
import { Loader2, ShieldCheck, PauseCircle, PlayCircle, Trash2, Download } from "lucide-react";
import { apiFetch } from "@/lib/api";

// Memory Control Center — Privacy panel. Available to ALL signed-in users.
// Drives the /api/memory-center endpoints (settings / purge / export).

const BASE = "/companion/api/memory-center";

// The 8 toggleable sensitivity classes (backend SENSITIVITY_TAGS minus "none").
const SENSITIVITY_TAGS: { id: string; label: string }[] = [
  { id: "health",           label: "Health" },
  { id: "mental-health",    label: "Mental health" },
  { id: "location",         label: "Location" },
  { id: "financial",        label: "Financial" },
  { id: "sexual",           label: "Sexual" },
  { id: "family",           label: "Family" },
  { id: "religion-beliefs", label: "Religion / beliefs" },
  { id: "political-views",  label: "Political views" },
];

interface Settings {
  disabled_sensitivities?: string[];
  collection_paused?: boolean;
  paused_until?: string | null;
}

const CARD: React.CSSProperties = {
  background: "rgba(255,255,255,0.03)",
  borderColor: "rgba(255,255,255,0.07)",
};

export function MemoryPrivacyPanel() {
  const [settings, setSettings] = useState<Settings>({});
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [purging, setPurging] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const r = await apiFetch(BASE);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setSettings(d.settings ?? {});
      setCount((d.memories?.length ?? 0) + (d.core_facts?.length ?? 0));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const patchSettings = useCallback(async (update: Settings) => {
    setSaving(true); setError("");
    setSettings((prev) => ({ ...prev, ...update })); // optimistic
    try {
      const r = await apiFetch(`${BASE}/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSettings(await r.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
      await load(); // revert to server truth
    } finally { setSaving(false); }
  }, [load]);

  const disabled = new Set(settings.disabled_sensitivities ?? []);

  const toggleTag = useCallback((tag: string) => {
    const next = new Set(settings.disabled_sensitivities ?? []);
    if (next.has(tag)) next.delete(tag); else next.add(tag);
    patchSettings({ disabled_sensitivities: Array.from(next) });
  }, [settings.disabled_sensitivities, patchSettings]);

  const togglePause = useCallback(() => {
    patchSettings({ collection_paused: !settings.collection_paused });
  }, [settings.collection_paused, patchSettings]);

  const purge = useCallback(async (tag: string, label: string) => {
    if (!window.confirm(`Permanently delete ALL stored ${label} memories? This cannot be undone.`)) return;
    setPurging(tag); setError("");
    try {
      const r = await apiFetch(`${BASE}/purge?sensitivity=${encodeURIComponent(tag)}`, { method: "POST" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    } finally { setPurging(null); }
  }, [load]);

  const exportMd = useCallback(async () => {
    setExporting(true); setError("");
    try {
      const r = await apiFetch(`${BASE}/export?format=md`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const text = await r.text();
      const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
      const a = document.createElement("a");
      a.href = url; a.download = "my-memories.md"; a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally { setExporting(false); }
  }, []);

  if (loading) {
    return (
      <div className="flex justify-center py-10">
        <Loader2 className="w-5 h-5 animate-spin text-violet-400" />
      </div>
    );
  }

  const paused = !!settings.collection_paused;

  return (
    <div className="space-y-5 pt-2">
      <div>
        <h2 className="text-white font-semibold text-sm flex items-center gap-1.5">
          <ShieldCheck className="w-4 h-4 text-violet-400" /> Memory &amp; Privacy
        </h2>
        <p className="text-white/30 text-[11px] mt-0.5">
          Control what your companion is allowed to remember. {count} item{count === 1 ? "" : "s"} stored.
        </p>
      </div>

      {error && <p className="text-[11px] text-rose-400">{error}</p>}

      {/* Pause collection */}
      <div className="rounded-xl border px-3 py-3 flex items-center justify-between" style={CARD}>
        <div>
          <p className="text-white/80 text-xs font-medium">Pause memory collection</p>
          <p className="text-white/35 text-[10px] mt-0.5">While paused, nothing new is remembered.</p>
        </div>
        <button
          onClick={togglePause}
          disabled={saving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition disabled:opacity-50"
          style={{
            background: paused ? "rgba(251,191,36,0.15)" : "rgba(255,255,255,0.06)",
            color: paused ? "rgb(251,191,36)" : "rgba(255,255,255,0.6)",
          }}
        >
          {paused
            ? <><PauseCircle className="w-3.5 h-3.5" /> Paused</>
            : <><PlayCircle className="w-3.5 h-3.5" /> Active</>}
        </button>
      </div>

      {/* Sensitivity category toggles */}
      <div className="space-y-1.5">
        <p className="text-white/50 text-[11px] font-medium px-0.5">Never remember these categories</p>
        {SENSITIVITY_TAGS.map((t) => {
          const off = disabled.has(t.id);
          return (
            <div key={t.id} className="rounded-xl border px-3 py-2 flex items-center justify-between" style={CARD}>
              <span className="text-white/75 text-xs">{t.label}</span>
              <div className="flex items-center gap-2.5">
                <button
                  onClick={() => purge(t.id, t.label)}
                  disabled={purging === t.id}
                  title={`Delete existing ${t.label.toLowerCase()} memories`}
                  className="p-1 rounded-lg text-white/25 hover:text-rose-400 transition disabled:opacity-40"
                >
                  {purging === t.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                </button>
                <button
                  onClick={() => toggleTag(t.id)}
                  disabled={saving}
                  role="switch"
                  aria-checked={off}
                  title={off ? "Currently blocked — click to allow" : "Click to never remember this category"}
                  className="relative w-9 h-5 rounded-full transition disabled:opacity-50"
                  style={{ background: off ? "rgba(124,58,237,0.75)" : "rgba(255,255,255,0.12)" }}
                >
                  <span
                    className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all"
                    style={{ left: off ? "1.125rem" : "0.125rem" }}
                  />
                </button>
              </div>
            </div>
          );
        })}
        <p className="text-white/25 text-[10px] px-0.5 pt-1 leading-relaxed">
          Toggle ON = your companion will never store that category from now on. The trash icon deletes
          what's already stored in that category.
        </p>
      </div>

      {/* Export */}
      <div className="pt-1">
        <button
          onClick={exportMd}
          disabled={exporting}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl text-xs font-medium text-white/70 border border-white/10 hover:bg-white/05 transition disabled:opacity-50"
        >
          {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
          Export my memories (Markdown)
        </button>
      </div>
    </div>
  );
}
