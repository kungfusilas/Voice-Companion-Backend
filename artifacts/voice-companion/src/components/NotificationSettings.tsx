/**
 * NotificationSettings — push notification opt-in/out toggle for authenticated users.
 */
import { useEffect, useState } from "react";
import { Bell, BellOff, Loader2, CheckCircle, XCircle } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { usePushNotifications } from "@/hooks/usePushNotifications";

export function NotificationSettings() {
  const { supported, subscribed, loading, subscribe, unsubscribe } = usePushNotifications();
  const [token, setToken] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setToken(session?.access_token ?? null);
    });
  }, []);

  async function handleToggle() {
    if (!token) return;
    setFeedback(null);
    let ok: boolean;
    if (subscribed) {
      ok = await unsubscribe(token);
      setFeedback(ok
        ? { ok: true,  msg: "Notifications turned off." }
        : { ok: false, msg: "Could not unsubscribe. Try again." });
    } else {
      ok = await subscribe(token);
      if (ok) {
        setFeedback({ ok: true, msg: "Notifications enabled! You'll get daily questions at 9am." });
      } else {
        setFeedback({ ok: false, msg: "Permission denied or not supported. Check your browser settings." });
      }
    }
  }

  if (!supported) {
    return (
      <div className="rounded-2xl p-5" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}>
        <div className="flex items-center gap-3 mb-2">
          <BellOff className="w-5 h-5 text-white/30" />
          <span className="text-white/50 text-sm font-medium">Push Notifications</span>
        </div>
        <p className="text-white/30 text-xs leading-relaxed">
          Push notifications aren't supported in this browser. Try Chrome or Firefox.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl p-5" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <div
            className="w-9 h-9 rounded-xl flex items-center justify-center"
            style={{ background: subscribed ? "rgba(139,92,246,0.15)" : "rgba(255,255,255,0.06)" }}
          >
            {subscribed
              ? <Bell className="w-4.5 h-4.5 text-violet-400" />
              : <BellOff className="w-4.5 h-4.5 text-white/30" />}
          </div>
          <div>
            <p className="text-white/80 text-sm font-medium">Daily Questions</p>
            <p className="text-white/35 text-xs">Push at 9am · reflections + check-ins</p>
          </div>
        </div>

        {/* Toggle */}
        <button
          onClick={handleToggle}
          disabled={loading || !token}
          className="relative w-12 h-6 rounded-full transition-colors duration-200 focus:outline-none disabled:opacity-40"
          style={{ background: subscribed ? "rgba(139,92,246,0.7)" : "rgba(255,255,255,0.12)" }}
          aria-label={subscribed ? "Disable notifications" : "Enable notifications"}
        >
          {loading ? (
            <Loader2 className="w-3.5 h-3.5 text-white animate-spin absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" />
          ) : (
            <span
              className="absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-all duration-200"
              style={{ left: subscribed ? "calc(100% - 1.375rem)" : "0.125rem" }}
            />
          )}
        </button>
      </div>

      {/* Status line */}
      <p className="text-white/25 text-[11px] leading-relaxed mb-3">
        {subscribed
          ? "You'll receive daily reflection questions and check-ins from AEVA."
          : "Get daily questions from AEVA directly to your device — even when the app is closed."}
      </p>

      {/* Feedback */}
      {feedback && (
        <div
          className="flex items-center gap-2 rounded-xl px-3 py-2 text-xs"
          style={{
            background: feedback.ok ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)",
            border: `1px solid ${feedback.ok ? "rgba(34,197,94,0.18)" : "rgba(239,68,68,0.18)"}`,
            color: feedback.ok ? "rgba(134,239,172,0.9)" : "rgba(252,165,165,0.9)",
          }}
        >
          {feedback.ok
            ? <CheckCircle className="w-3.5 h-3.5 shrink-0" />
            : <XCircle className="w-3.5 h-3.5 shrink-0" />}
          {feedback.msg}
        </div>
      )}

      {/* Weekly themes preview */}
      {subscribed && (
        <div className="mt-3 pt-3" style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
          <p className="text-white/25 text-[11px] uppercase tracking-wider mb-2">Weekly themes</p>
          {["Origins & Identity", "Love & Connection", "Growth & Becoming", "Legacy & Meaning"].map((theme) => (
            <p key={theme} className="text-white/30 text-[11px] leading-relaxed">· {theme}</p>
          ))}
        </div>
      )}
    </div>
  );
}
