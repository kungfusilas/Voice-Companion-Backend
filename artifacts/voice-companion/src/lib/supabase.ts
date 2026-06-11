import { createClient, SupabaseClient } from "@supabase/supabase-js";

function buildClient(): { client: SupabaseClient; configured: boolean } {
  const rawUrl = (import.meta.env.VITE_SUPABASE_URL as string | undefined) ?? "";
  const rawKey = (import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined) ?? "";

  // Normalize URL — ensure it has an https:// scheme.
  const url = rawUrl
    ? rawUrl.startsWith("http")
      ? rawUrl.trim()
      : `https://${rawUrl.trim()}`
    : "";

  const configured = !!url && !!rawKey;

  try {
    const client = createClient(
      configured ? url : "https://placeholder.supabase.co",
      configured ? rawKey : "placeholder-anon-key",
      {
        auth: {
          // Use localStorage so sessions survive page reloads and mobile
          // app backgrounding (sessionStorage is cleared when iOS unloads
          // the page, which silently logs users out on every return visit).
          storage: window.localStorage,
          persistSession: true,
          autoRefreshToken: true,
          // Disable auto-detection: AuthCallback handles the ?code= exchange
          // explicitly. Keeping this true alongside manual exchangeCodeForSession
          // would cause a double-exchange race (second call fails "code already used").
          detectSessionInUrl: false,
          // PKCE is the current standard for browser OAuth. The SDK stores the
          // code verifier in localStorage during signInWithOAuth so it is
          // available when AuthCallback calls exchangeCodeForSession on return.
          flowType: "pkce",
        },
      }
    );
    return { client, configured };
  } catch {
    // If createClient still throws (e.g. env var is garbage), return a
    // placeholder client built from safe values so the module never crashes.
    const client = createClient(
      "https://placeholder.supabase.co",
      "placeholder-anon-key",
    );
    return { client, configured: false };
  }
}

const { client, configured } = buildClient();

export const supabase: SupabaseClient = client;
export const SUPABASE_CONFIGURED: boolean = configured;
