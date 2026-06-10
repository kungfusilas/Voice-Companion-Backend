import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Zap, Clock } from "lucide-react";
import { createCheckoutSession } from "@/lib/api";

export interface QuotaDetail {
  kind: string;
  renews_at: string | null;
  packs: { key: string; name: string; price: string; credits: number }[];
}

interface QuotaModalProps {
  detail: QuotaDetail | null;
  onClose: () => void;
  onUpgrade: () => void;
}

function formatRenewsAt(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "long", day: "numeric" });
  } catch {
    return iso;
  }
}

export function QuotaModal({ detail, onClose, onUpgrade }: QuotaModalProps) {
  const [loading, setLoading] = useState<string | null>(null);

  if (!detail) return null;

  const kindLabel = detail.kind === "voice" ? "voice minutes" : "messages";
  const kindIcon  = detail.kind === "voice" ? "🎙️" : "💬";

  const handleBuyPack = async (packKey: string) => {
    if (loading) return;
    setLoading(packKey);
    try {
      const { url } = await createCheckoutSession(packKey);
      window.location.href = url;
    } catch {
      setLoading(null);
    }
  };

  return (
    <AnimatePresence>
      {detail && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.78)", backdropFilter: "blur(6px)" }}
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.92, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.92, y: 12 }}
            transition={{ type: "spring", damping: 24, stiffness: 300 }}
            className="relative w-full max-w-xs rounded-2xl p-5 text-center"
            style={{
              background: "rgba(12,6,26,0.98)",
              border: "1px solid rgba(255,255,255,0.12)",
              boxShadow: "0 28px 72px rgba(0,0,0,0.75)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={onClose}
              className="absolute top-3 right-3 text-white/25 hover:text-white/55 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>

            <div className="text-3xl mb-2">{kindIcon}</div>
            <h3 className="text-white font-semibold text-base mb-1">
              Monthly {kindLabel} used up
            </h3>

            {detail.renews_at && (
              <p className="text-white/35 text-xs mb-4 flex items-center justify-center gap-1.5">
                <Clock className="w-3 h-3 shrink-0" />
                Resets {formatRenewsAt(detail.renews_at)}
              </p>
            )}

            {detail.packs.length > 0 && (
              <>
                <p className="text-white/50 text-xs mb-2.5">Add more {kindLabel} now:</p>
                <div className="space-y-2 mb-4">
                  {detail.packs.map((pack) => (
                    <button
                      key={pack.key}
                      onClick={() => handleBuyPack(pack.key)}
                      disabled={!!loading}
                      className="w-full flex items-center justify-between px-4 py-2.5 rounded-xl text-sm font-medium transition-all hover:opacity-90 disabled:opacity-50"
                      style={{
                        background: loading === pack.key
                          ? "rgba(124,58,237,0.08)"
                          : "rgba(124,58,237,0.14)",
                        border: "1px solid rgba(124,58,237,0.28)",
                        color: "white",
                      }}
                    >
                      <span className="flex items-center gap-2">
                        <Zap className="w-3.5 h-3.5 text-violet-400 shrink-0" />
                        {pack.name}
                      </span>
                      <span className="text-violet-300 font-semibold shrink-0">
                        {loading === pack.key ? "…" : pack.price}
                      </span>
                    </button>
                  ))}
                </div>
              </>
            )}

            <div className="border-t border-white/08 pt-3">
              <button
                onClick={onUpgrade}
                className="text-xs text-violet-400 hover:text-violet-300 transition-colors"
              >
                Or upgrade your plan for a higher monthly allowance →
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
