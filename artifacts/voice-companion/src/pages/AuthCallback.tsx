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
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const errorParam = params.get("error");
    const errorDescription = params.get("error_description");

    console.log("[AuthCallback] URL search:", window.location.search);
    console.log("[AuthCallback] code:", code ? code.slice(0, 8) + "…" : null);
    console.log("[AuthCallback] error param:", errorParam, errorDescription);

    if (errorParam) {
      const msg = errorDescription ?? errorParam;
      console.error("[AuthCallback] OAuth error from provider:", msg);
      setStatus("error");
      setErrorMsg(msg);
      setTimeout(onError, 2500);
      return;
    }

    if (!code) {
      const msg = "No authorization code found in URL.";
      console.error("[AuthCallback]", msg);
      setStatus("error");
      setErrorMsg(msg);
      setTimeout(onError, 2000);
      return;
    }

    // Must pass just the raw code string — NOT window.location.search or full URL
    console.log("[AuthCallback] calling exchangeCodeForSession…");
    supabase.auth
      .exchangeCodeForSession(code)
      .then(({ data, error }) => {
        if (error) {
          console.error("[AuthCallback] exchangeCodeForSession error:", {
            message: error.message,
            status: error.status,
            name: error.name,
          });
          setStatus("error");
          setErrorMsg(error.message);
          setTimeout(onError, 2500);
        } else {
          console.log("[AuthCallback] exchange succeeded, user:", data.session?.user?.email);
          window.history.replaceState({}, "", "/companion/");
          onSuccess();
        }
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        console.error("[AuthCallback] unexpected error:", msg);
        setStatus("error");
        setErrorMsg(msg);
        setTimeout(onError, 2500);
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
