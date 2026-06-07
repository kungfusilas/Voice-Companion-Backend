import { createClient, SupabaseClient } from "@supabase/supabase-js";

// Use sessionStorage instead of localStorage so auth tokens do not persist
// across browser sessions (more secure; user logs in fresh per tab session).
const sessionStorageAdapter = {
  getItem: (key: string): string | null => sessionStorage.getItem(key),
  setItem: (key: string, value: string): void =>
    sessionStorage.setItem(key, value),
  removeItem: (key: string): void => sessionStorage.removeItem(key),
};

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
          storage: sessionStorageAdapter,
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true,
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
      { auth: { storage: sessionStorageAdapter } }
    );
    return { client, configured: false };
  }
}

const { client, configured } = buildClient();

export const supabase: SupabaseClient = client;
export const SUPABASE_CONFIGURED: boolean = configured;
