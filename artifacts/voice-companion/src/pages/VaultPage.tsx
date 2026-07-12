import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Archive, ScrollText, Heart, Trash2, Download, Loader, ChevronLeft, Image as ImageIcon } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface VaultPageProps {
  userId: string;
  onBack: () => void;
}

interface VaultSession {
  id: string;
  title: string;
  message_count: number;
  created_at: string;
  messages?: Array<{ role: string; content: string }>;
}

interface Recipient {
  name: string;
  email: string;
  relationship?: string;
  personal_message?: string;
  inactivity_days: number;
}

const INACTIVITY_OPTIONS = [
  { label: "30 days", value: 30 },
  { label: "90 days", value: 90 },
  { label: "6 months", value: 180 },
  { label: "1 year", value: 365 },
  { label: "2 years", value: 730 },
];

interface VaultFile {
  id: string;
  url: string;
  filename?: string;
  uploaded_at?: string;
}

type Tab = "conversations" | "files" | "legacy";

export function VaultPage({ userId, onBack }: VaultPageProps) {
  const [tab, setTab] = useState<Tab>("conversations");
  const [sessions, setSessions] = useState<VaultSession[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [files, setFiles] = useState<VaultFile[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(true);
  const [recipient, setRecipient] = useState<Partial<Recipient>>({ inactivity_days: 365 });
  const [savingRecipient, setSavingRecipient] = useState(false);
  const [recipientSaved, setRecipientSaved] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);

  useEffect(() => {
    fetchSessions();
    fetchRecipient();
    fetchFiles();
  }, []);

  async function fetchSessions() {
    setLoadingSessions(true);
    try {
      const r = await apiFetch(`/companion/api/vault/sessions?user_id=${userId}`);
      if (r.ok) setSessions(await r.json());
    } finally {
      setLoadingSessions(false);
    }
  }

  async function fetchFiles() {
    setLoadingFiles(true);
    try {
      const r = await apiFetch(`/companion/api/vault/files?user_id=${userId}`);
      if (r.ok) {
        const data = await r.json();
        setFiles(Array.isArray(data.files) ? data.files : []);
      }
    } finally {
      setLoadingFiles(false);
    }
  }

  async function fetchRecipient() {
    const r = await apiFetch(`/companion/api/vault/recipient?user_id=${userId}`);
    if (r.ok) {
      const data = await r.json();
      if (data) setRecipient(data);
    }
  }

  async function deleteSession(id: string) {
    await apiFetch(`/companion/api/vault/sessions/${id}?user_id=${userId}`, { method: "DELETE" });
    setSessions((s) => s.filter((x) => x.id !== id));
  }

  async function downloadSession(session: VaultSession) {
    setDownloading(session.id);
    try {
      const r = await apiFetch(`/companion/api/vault/sessions/${session.id}?user_id=${userId}`);
      if (!r.ok) return;
      const full = await r.json();
      const lines = (full.messages || []).map((m: { role: string; content: string }) =>
        `[${m.role.toUpperCase()}]\n${m.content}\n`
      );
      const text = `${full.title}\n${"=".repeat(full.title.length)}\n\n${lines.join("\n")}`;
      const blob = new Blob([text], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${full.title.replace(/[^a-z0-9]/gi, "_")}.txt`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(null);
    }
  }

  async function saveRecipient() {
    if (!recipient.name || !recipient.email) return;
    setSavingRecipient(true);
    try {
      await apiFetch("/companion/api/vault/recipient", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...recipient, user_id: userId }),
      });
      setRecipientSaved(true);
      setTimeout(() => setRecipientSaved(false), 3000);
    } finally {
      setSavingRecipient(false);
    }
  }

  return (
    <div className="flex flex-col h-full bg-[#0a0a0f] text-white">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-white/5 shrink-0">
        <button onClick={onBack} className="text-white/40 hover:text-white/70 transition-colors p-1">
          <ChevronLeft className="w-5 h-5" />
        </button>
        <Archive className="w-5 h-5 text-purple-400" />
        <h2 className="text-white font-semibold text-sm">Legacy Vault</h2>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-white/5 shrink-0">
        {([
          { id: "conversations" as Tab, label: "Conversations", icon: ScrollText },
          { id: "files" as Tab, label: "Files", icon: ImageIcon },
          { id: "legacy" as Tab, label: "Legacy Settings", icon: Heart },
        ] as const).map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex-1 flex items-center justify-center gap-2 py-3 text-xs font-medium border-b-2 transition-colors ${
              tab === id
                ? "border-purple-500 text-purple-400"
                : "border-transparent text-white/30 hover:text-white/50"
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        <AnimatePresence mode="wait">
          {tab === "conversations" ? (
            <motion.div key="conversations" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-3">
              {loadingSessions ? (
                <div className="flex justify-center py-12">
                  <Loader className="w-5 h-5 text-purple-400 animate-spin" />
                </div>
              ) : sessions.length === 0 ? (
                <div className="text-center py-16">
                  <ScrollText className="w-10 h-10 mx-auto mb-3 text-white/10" />
                  <p className="text-sm text-white/30">No saved conversations yet.</p>
                  <p className="text-xs text-white/20 mt-1">Use the vault button during a chat to save a meaningful session.</p>
                </div>
              ) : (
                sessions.map((s) => (
                  <div key={s.id} className="flex items-start justify-between gap-3 bg-white/5 border border-white/10 rounded-xl p-4">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-white font-medium leading-snug">{s.title}</p>
                      <p className="text-xs text-white/30 mt-1">{s.message_count} messages</p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => downloadSession(s)}
                        disabled={downloading === s.id}
                        className="text-white/25 hover:text-purple-400 transition-colors"
                        title="Download conversation"
                      >
                        {downloading === s.id
                          ? <Loader className="w-4 h-4 animate-spin" />
                          : <Download className="w-4 h-4" />
                        }
                      </button>
                      <button
                        onClick={() => deleteSession(s.id)}
                        className="text-white/20 hover:text-red-400 transition-colors"
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ))
              )}
            </motion.div>
          ) : tab === "files" ? (
            <motion.div key="files" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              {loadingFiles ? (
                <div className="flex justify-center py-12">
                  <Loader className="w-5 h-5 text-purple-400 animate-spin" />
                </div>
              ) : files.length === 0 ? (
                <div className="text-center py-16">
                  <ImageIcon className="w-10 h-10 mx-auto mb-3 text-white/10" />
                  <p className="text-sm text-white/30">No photos shared yet.</p>
                  <p className="text-xs text-white/20 mt-1">Photos you share in chat are saved here automatically.</p>
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-2">
                  {files.map((f) => (
                    <a
                      key={f.id}
                      href={f.url}
                      target="_blank"
                      rel="noreferrer"
                      className="block aspect-square rounded-xl overflow-hidden border border-white/10 bg-white/5"
                    >
                      <img src={f.url} alt={f.filename || "Vault photo"} className="w-full h-full object-cover" loading="lazy" />
                    </a>
                  ))}
                </div>
              )}
            </motion.div>
          ) : (
            <motion.div key="legacy" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-4">
              <p className="text-xs text-white/40 leading-relaxed">
                If you go inactive for the set period, your Legacy Vault will be delivered to this person. You'll receive a check-in email before anything is sent.
              </p>
              <div className="space-y-3">
                <input
                  value={recipient.name || ""}
                  onChange={(e) => setRecipient((r) => ({ ...r, name: e.target.value }))}
                  placeholder="Recipient's full name"
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder:text-white/25 focus:outline-none focus:border-purple-500/50"
                />
                <input
                  value={recipient.email || ""}
                  onChange={(e) => setRecipient((r) => ({ ...r, email: e.target.value }))}
                  placeholder="Recipient's email"
                  type="email"
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder:text-white/25 focus:outline-none focus:border-purple-500/50"
                />
                <input
                  value={recipient.relationship || ""}
                  onChange={(e) => setRecipient((r) => ({ ...r, relationship: e.target.value }))}
                  placeholder="Relationship (e.g. daughter, best friend)"
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder:text-white/25 focus:outline-none focus:border-purple-500/50"
                />
                <textarea
                  value={recipient.personal_message || ""}
                  onChange={(e) => setRecipient((r) => ({ ...r, personal_message: e.target.value }))}
                  placeholder="A personal message to include when your vault is delivered..."
                  rows={3}
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder:text-white/25 resize-none focus:outline-none focus:border-purple-500/50"
                />
              </div>
              <div>
                <p className="text-xs text-white/40 mb-2">Deliver vault after inactivity of:</p>
                <div className="grid grid-cols-3 gap-2">
                  {INACTIVITY_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setRecipient((r) => ({ ...r, inactivity_days: opt.value }))}
                      className={`py-2 rounded-xl text-xs font-medium transition-colors ${
                        recipient.inactivity_days === opt.value
                          ? "bg-purple-600 text-white"
                          : "bg-white/5 text-white/40 hover:text-white/60"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
              <button
                onClick={saveRecipient}
                disabled={!recipient.name || !recipient.email || savingRecipient}
                className="w-full py-3 bg-purple-600 hover:bg-purple-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-xl transition-colors"
              >
                {savingRecipient ? "Saving..." : recipientSaved ? "✓ Saved" : "Save Legacy Settings"}
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
