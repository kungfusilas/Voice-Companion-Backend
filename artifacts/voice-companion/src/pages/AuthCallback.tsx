import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

const BG: React.CSSProperties = {
  background: "linear-gradient(145deg, #0d0d1a 0%, #0f0720 50%, #0d0d1a 100%)",
};

interface Props {
  onSuccess: () => void;
  onError: () => void;
}

export function AuthCallback({ onSuccess, onError }: Props) {
  const [status, setStatus] = useState<"exchanging" | "error">("exchanging");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get("code");

    if (!code) {
      setStatus("error");
      setErrorMsg("No authorization code found in URL.");
      setTimeout(onError, 2000);
      return;
    }

    supabase.auth
      .exchangeCodeForSession(window.location.search)
      .then(({ error }) => {
        if (error) {
          setStatus("error");
          setErrorMsg(error.message);
          setTimeout(onError, 2500);
        } else {
          // Session is now set — onAuthStateChange in App.tsx will also fire,
          // but we navigate directly here for speed.
          window.history.replaceState({}, "", "/companion/");
          onSuccess();
        }
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="min-h-screen flex items-center justify-center" style={BG}>
      <div className="flex flex-col items-center gap-4">
        {status === "exchanging" ? (
          <>
            <div className="w-8 h-8 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
            <p className="text-white/50 text-sm">Signing you in…</p>
          </>
        ) : (
          <>
            <p className="text-red-400 text-sm">Sign-in failed</p>
            {errorMsg && (
              <p className="text-white/40 text-xs max-w-xs text-center">{errorMsg}</p>
            )}
            <p className="text-white/30 text-xs">Redirecting back…</p>
          </>
        )}
      </div>
    </div>
  );
}
