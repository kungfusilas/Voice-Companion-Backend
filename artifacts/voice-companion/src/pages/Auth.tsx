import { useState, useEffect } from "react";
import { supabase } from "@/lib/supabase";
import { FaGoogle, FaApple } from "react-icons/fa";

const ROTATING_LINES = [
  "Build Better Relationships",
  "Your AI Companion for Real Connection",
  "Every Conversation Matters",
  "Companionship That Grows With You",
  "The AI That Helps You Connect",
  "Strengthen Every Relationship",
  "Remember More. Connect Better.",
  "Your Personal Relationship Coach",
];

interface Props {
  onAuth: () => void;
}

type Mode = "signin" | "signup";

const BG: React.CSSProperties = {
  background: "linear-gradient(145deg, #0d0d1a 0%, #0f0720 50%, #0d0d1a 100%)",
};

const CARD: React.CSSProperties = {
  background: "rgba(255,255,255,0.03)",
  backdropFilter: "blur(20px)",
  border: "1px solid rgba(255,255,255,0.08)",
  boxShadow: "0 30px 80px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.06)",
};

export function AuthPage({ onAuth }: Props) {
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [oauthLoading, setOauthLoading] = useState<"google" | "apple" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [taglineIdx, setTaglineIdx] = useState(0);
  const [taglineFade, setTaglineFade] = useState(true);

  useEffect(() => {
    const iv = setInterval(() => {
      setTaglineFade(false);
      setTimeout(() => {
        setTaglineIdx((i) => (i + 1) % ROTATING_LINES.length);
        setTaglineFade(true);
      }, 400);
    }, 3000);
    return () => clearInterval(iv);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setLoading(true);

    try {
      if (mode === "signup") {
        const { error } = await supabase.auth.signUp({ email, password });
        if (error) throw error;
        setMessage("Check your email to confirm your account, then sign in.");
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        onAuth();
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  const handleOAuth = async (provider: "google" | "apple") => {
    setError(null);
    setOauthLoading(provider);
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider,
        options: {
          // After OAuth completes, Supabase redirects here.
          // Configure this URL in: Supabase Dashboard → Authentication → URL Configuration
          redirectTo: `${window.location.origin}/companion/`,
        },
      });
      if (error) throw error;
      // Browser will redirect — no further action needed here
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "OAuth sign-in failed");
      setOauthLoading(null);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={BG}>
      <div className="w-full max-w-sm rounded-3xl overflow-hidden" style={CARD}>
        {/* Header */}
        <div className="px-8 pt-10 pb-6 text-center">
          <div className="w-12 h-12 mx-auto mb-4 rounded-2xl bg-violet-600/30 border border-violet-500/30 flex items-center justify-center">
            <span className="text-2xl">✦</span>
          </div>
          <h1 className="text-xl font-semibold text-white tracking-tight">BondAI</h1>
          <p className="text-white/40 text-sm mt-1">An AI that remembers who you're becoming.</p>
          <p
            className="text-white/25 text-xs mt-1.5 transition-opacity duration-400"
            style={{ opacity: taglineFade ? 1 : 0 }}
          >
            {ROTATING_LINES[taglineIdx]}
          </p>
        </div>

        {/* Mode toggle */}
        <div className="px-8 mb-6">
          <div className="flex rounded-xl overflow-hidden border border-white/08 bg-white/[0.03]">
            <button
              type="button"
              onClick={() => { setMode("signin"); setError(null); setMessage(null); }}
              className={`flex-1 py-2.5 text-sm font-medium transition-all duration-200 ${
                mode === "signin"
                  ? "bg-violet-600/40 text-white"
                  : "text-white/40 hover:text-white/60"
              }`}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => { setMode("signup"); setError(null); setMessage(null); }}
              className={`flex-1 py-2.5 text-sm font-medium transition-all duration-200 ${
                mode === "signup"
                  ? "bg-violet-600/40 text-white"
                  : "text-white/40 hover:text-white/60"
              }`}
            >
              Sign Up
            </button>
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="px-8 space-y-3">
          <div>
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className="w-full px-4 py-3 rounded-xl bg-white/[0.05] border border-white/10 text-white placeholder-white/30 text-sm focus:outline-none focus:border-violet-500/60 transition-colors"
            />
          </div>
          <div>
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
              className="w-full px-4 py-3 rounded-xl bg-white/[0.05] border border-white/10 text-white placeholder-white/30 text-sm focus:outline-none focus:border-violet-500/60 transition-colors"
            />
          </div>

          {/* Error / message */}
          {error && (
            <p className="text-red-400/90 text-xs text-center py-1">{error}</p>
          )}
          {message && (
            <p className="text-emerald-400/90 text-xs text-center py-1">{message}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-all duration-200 mt-1"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                {mode === "signup" ? "Creating account…" : "Signing in…"}
              </span>
            ) : mode === "signup" ? (
              "Create Account"
            ) : (
              "Sign In"
            )}
          </button>
        </form>

        {/* Divider */}
        <div className="px-8 my-5 flex items-center gap-3">
          <div className="flex-1 h-px bg-white/08" />
          <span className="text-white/25 text-xs">or continue with</span>
          <div className="flex-1 h-px bg-white/08" />
        </div>

        {/* OAuth buttons */}
        <div className="px-8 pb-10 space-y-3">
          <button
            type="button"
            onClick={() => handleOAuth("google")}
            disabled={!!oauthLoading}
            className="w-full py-3 rounded-xl bg-white hover:bg-white/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-3 text-sm font-medium text-gray-800 transition-all duration-200"
          >
            {oauthLoading === "google" ? (
              <span className="w-4 h-4 border-2 border-gray-400 border-t-gray-800 rounded-full animate-spin" />
            ) : (
              <FaGoogle className="text-[#4285F4] text-base" />
            )}
            Continue with Google
          </button>

          <button
            type="button"
            onClick={() => handleOAuth("apple")}
            disabled={!!oauthLoading}
            className="w-full py-3 rounded-xl bg-black hover:bg-black/80 disabled:opacity-50 disabled:cursor-not-allowed border border-white/15 flex items-center justify-center gap-3 text-sm font-medium text-white transition-all duration-200"
          >
            {oauthLoading === "apple" ? (
              <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            ) : (
              <FaApple className="text-white text-base" />
            )}
            Continue with Apple
          </button>
        </div>
      </div>
    </div>
  );
}
