import { createClient } from "@supabase/supabase-js";

// Fallback placeholders allow the module to load even before env vars are set.
// The app detects the unconfigured state via SUPABASE_CONFIGURED and shows a
// setup screen rather than crashing.
const rawUrl = (import.meta.env.VITE_SUPABASE_URL as string | undefined) || "";

// Normalize: ensure URL has https:// prefix (guards against accidentally
// pasting just the subdomain without the scheme).
const supabaseUrl = rawUrl
  ? rawUrl.startsWith("http")
    ? rawUrl
    : `https://${rawUrl}`
  : "https://placeholder.supabase.co";

const supabaseAnonKey =
  (import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined) ||
  "placeholder-anon-key";

export const SUPABASE_CONFIGURED =
  !!import.meta.env.VITE_SUPABASE_URL &&
  !!import.meta.env.VITE_SUPABASE_ANON_KEY;

// Use sessionStorage instead of localStorage so auth tokens do not persist
// across browser sessions (more secure; user logs in fresh per tab session).
const sessionStorageAdapter = {
  getItem: (key: string): string | null => sessionStorage.getItem(key),
  setItem: (key: string, value: string): void =>
    sessionStorage.setItem(key, value),
  removeItem: (key: string): void => sessionStorage.removeItem(key),
};

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    storage: sessionStorageAdapter,
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});
