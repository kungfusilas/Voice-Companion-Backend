import { supabase } from "@/lib/supabase";

const BASE = "/companion/api";

// ── Auth helper ───────────────────────────────────────────────────────────────

/**
 * Central fetch wrapper — automatically attaches the Supabase Bearer token
 * to every request.  Falls back gracefully if no session exists yet.
 */
async function apiFetch(input: RequestInfo, init: RequestInit = {}): Promise<Response> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;
  const guestId = !token ? localStorage.getItem("bondai_guest_id") : null;
  const sessionId = sessionStorage.getItem("bondai_session_id");

  return fetch(input, {
    ...init,
    headers: {
      ...(init.headers as Record<string, string> | undefined),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(guestId ? { "X-Guest-ID": guestId } : {}),
      ...(sessionId ? { "X-Session-Id": sessionId } : {}),
    },
  });
}

// Exported for Hub pages that need authenticated fetch
export { apiFetch };

export async function apiFetchJSON<T>(input: RequestInfo, init: RequestInit = {}): Promise<T> {
  const res = await apiFetch(input, init);
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json() as Promise<T>;
}

// ── Structured API error ──────────────────────────────────────────────────────

/** Thrown by API calls when the server returns a non-2xx status. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    public readonly detail: unknown,
  ) {
    super(code);
    Object.setPrototypeOf(this, ApiError.prototype);
  }
}

async function _parseErrorBody(res: Response): Promise<{ code: string; detail: unknown }> {
  let body: unknown;
  try { body = await res.clone().json(); } catch { body = await res.text(); }
  const d = (body as Record<string, unknown> | null)?.detail ?? body;
  const code = (d as Record<string, unknown> | null)?.code as string | undefined ?? String(res.status);
  return { code, detail: d };
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Persona {
  id: string;
  name: string;
  relationship_type: string;
  personality_traits: string[];
  backstory: string;
  custom_relationship: string;
  voice_id: string | null;
  nsfw_mode: boolean;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  proactive?: boolean;
  imageUrl?: string;
  activityData?: ActivityData;
}

export interface ChatResponse {
  session_id: string;
  persona_id: string;
  reply: string;
  message_count: number;
  model_backend: "claude" | "venice";
  connection_score: number;
  score_delta: number;
  relationship_type: string;
  stage_name: string;
  stage_min: number;
  stage_max: number;
  stage_up_text: string;
}

export interface RelationshipStats {
  user_id: string;
  companion_id: string;
  message_count: number;
  relationship_type: string | null;
  connection_score: number;
  drift_flag: boolean;
  drift_acknowledged_at: string | null;
  romantic_mode: boolean;
  romantic_mode_unlocked: boolean;
}

export interface UsageStatus {
  msgs_used: number;
  msgs_allowance: number;
  topup_msgs: number;
  voice_seconds_used: number;
  voice_allowance: number;
  topup_voice_seconds: number;
  usage_period_start: string | null;
  renews_at: string | null;
}

// ── Activities ────────────────────────────────────────────────────────────────

export type ActivityType = "word_game" | "trivia" | "would_you_rather";

export interface WordGameActivity {
  type: "word_game";
  clue1: string;
  clue2: string;
  clue3: string;
  answer: string;
  companion_intro: string;
  companion_id: string;
  companion_name: string;
}

export interface TriviaActivity {
  type: "trivia";
  question: string;
  options: { A: string; B: string; C: string; D: string };
  correct: "A" | "B" | "C" | "D";
  fun_fact: string;
  companion_intro: string;
  companion_id: string;
  companion_name: string;
}

export interface WouldYouRatherActivity {
  type: "would_you_rather";
  optionA: string;
  optionB: string;
  companion_choice: "A" | "B";
  companion_reason: string;
  companion_intro: string;
  companion_id: string;
  companion_name: string;
}

export type ActivityData = WordGameActivity | TriviaActivity | WouldYouRatherActivity;

// ── Personas ──────────────────────────────────────────────────────────────────

export async function listPersonas(): Promise<Persona[]> {
  const res = await apiFetch(`${BASE}/personas`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** Stub — custom persona creation is not active in this build. */
export async function createPersona(_data: unknown): Promise<Persona> {
  throw new Error("Custom persona creation is not enabled.");
}

// ── Relationship ──────────────────────────────────────────────────────────────

export async function getRelationshipStats(
  userId: string,
  companionId: string,
): Promise<RelationshipStats> {
  const res = await apiFetch(`${BASE}/relationship/${userId}/${companionId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function setRelationshipType(
  userId: string,
  companionId: string,
  relType: string,
): Promise<void> {
  const res = await apiFetch(`${BASE}/relationship/type`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, companion_id: companionId, relationship_type: relType }),
  });
  if (!res.ok) throw new Error(await res.text());
}

// ── Romantic Mode ─────────────────────────────────────────────────────────────

export async function setRomanticMode(
  userId: string,
  companionId: string,
  enabled: boolean,
): Promise<{ success: boolean; companion_reaction: string }> {
  const res = await apiFetch(`${BASE}/romantic-mode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, companion_id: companionId, enabled }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Chat (streaming) ──────────────────────────────────────────────────────────

export interface StreamEvent {
  type: "token" | "done" | "error" | "searching" | "waitlist_prompt";
  text?: string;
  query?: string;
  full_text?: string;
  message_count?: number;
  model_backend?: "claude" | "venice";
  message?: string;
  connection_score?: number;
  score_delta?: number;
  relationship_type?: string;
  stage_name?: string;
  stage_min?: number;
  stage_max?: number;
  stage_up_text?: string;
  companion_id?: string;
  usage?: { remaining: number; cap: number; warning: boolean; reset_date: string };
}

export async function uploadPhoto(
  file: File,
): Promise<{ storage_path: string; display_url: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiFetch(`${BASE}/photo/upload`, { method: "POST", body: form });
  if (!res.ok) {
    const { code, detail } = await _parseErrorBody(res);
    throw new ApiError(res.status, code, detail);
  }
  return res.json() as Promise<{ storage_path: string; display_url: string }>;
}

export async function* chatStream(
  session_id: string,
  persona_id: string,
  message: string,
  _user_id?: string,
  romantic_mode?: boolean,
  _nsfw_mode?: boolean,
  onboarding_context?: string,
  image_url?: string,
): AsyncGenerator<StreamEvent> {
  const res = await apiFetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id, persona_id, message,
      romantic_mode: romantic_mode ?? false,
      onboarding_context: onboarding_context ?? undefined,
      ...(image_url ? { image_url } : {}),
    }),
  });
  if (!res.ok || !res.body) {
    const { code, detail } = await _parseErrorBody(res);
    throw new ApiError(res.status, code, detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try { yield JSON.parse(line.slice(6)) as StreamEvent; } catch {}
    }
  }
}

// ── Onboarding / Wow moment ───────────────────────────────────────────────────

export interface WowResponse { message: string; }

export async function requestWowMoment(session_id: string, persona_id: string): Promise<WowResponse> {
  const res = await apiFetch(`${BASE}/onboarding/wow`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id, persona_id }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Memories ──────────────────────────────────────────────────────────────────

export interface Memory { id: string; content: string; created_at: string; }
export interface MemoriesResponse {
  user_id: string; persona_id: string; memories: Memory[]; count: number;
}

export async function fetchMemories(_user_id: string, persona_id: string): Promise<MemoriesResponse> {
  // user_id param kept for call-site compat; backend now reads it from JWT
  const params = new URLSearchParams({ persona_id });
  const res = await apiFetch(`${BASE}/memories?${params}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── STT ───────────────────────────────────────────────────────────────────────

/** Derive an audio file extension from a blob's mimeType for correct upload naming. */
function _audioExt(blob: Blob): string {
  const base = blob.type.split(";")[0].trim().toLowerCase();
  if (base === "audio/mp4" || base === "audio/m4a" || base === "audio/aac") return "m4a";
  if (base === "audio/ogg") return "ogg";
  if (base === "audio/wav" || base === "audio/x-wav") return "wav";
  return "webm"; // default / audio/webm
}

export async function transcribeAudio(blob: Blob): Promise<string> {
  const form = new FormData();
  form.append("audio", blob, `recording.${_audioExt(blob)}`);
  const res = await apiFetch(`${BASE}/stt`, { method: "POST", body: form });
  if (!res.ok) {
    const { code, detail } = await _parseErrorBody(res);
    throw new ApiError(res.status, code, detail);
  }
  return (await res.json()).transcript as string;
}

// ── TTS ───────────────────────────────────────────────────────────────────────

export async function speakText(text: string, persona_id: string, previous_text?: string): Promise<Blob> {
  const res = await apiFetch(`${BASE}/tts/speak`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, persona_id, ...(previous_text ? { previous_text } : {}) }),
  });
  if (!res.ok) {
    const { code, detail } = await _parseErrorBody(res);
    throw new ApiError(res.status, code, detail);
  }
  return res.blob();
}

/**
 * Like speakText but returns the raw streaming Response so the caller can
 * pipe it into an MSE SourceBuffer for near-instant playback.
 */
export async function speakTextStream(text: string, persona_id: string, previous_text?: string): Promise<Response> {
  const res = await apiFetch(`${BASE}/tts/speak/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, persona_id, ...(previous_text ? { previous_text } : {}) }),
  });
  if (!res.ok) {
    const { code, detail } = await _parseErrorBody(res);
    throw new ApiError(res.status, code, detail);
  }
  return res;
}

// ── Client diagnostics ────────────────────────────────────────────────────────

/**
 * Fire-and-forget: POST a structured log entry to the server so TTS pipeline
 * failures (AudioContext state, decode errors, play() rejections) are visible
 * in server logs with zero user effort. Silently dropped on auth/network failure.
 */
export function clientLog(event: string, data: Record<string, unknown> = {}): void {
  apiFetch(`${BASE}/client-log`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event, data }),
  }).catch(() => {});
}

// ── Usage ─────────────────────────────────────────────────────────────────────

export async function getUsageStatus(): Promise<UsageStatus> {
  const res = await apiFetch(`${BASE}/usage/status`);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<UsageStatus>;
}

export async function registerSession(sessionId: string): Promise<void> {
  await apiFetch(`${BASE}/session/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  // fire-and-forget — errors ignored
}

// ── Proactive messages ────────────────────────────────────────────────────────

export interface ProactiveMessage {
  id: string;
  message: string;
  sent_at: string;
  activity_type?: string;
  activity_data?: ActivityData;
}

export interface ProactiveMessagesResponse {
  user_id: string; companion_id: string; messages: ProactiveMessage[]; count: number;
}

export async function fetchProactiveMessages(
  user_id: string,
  companion_id: string,
): Promise<ProactiveMessagesResponse> {
  const res = await apiFetch(`${BASE}/proactive-messages/${user_id}/${companion_id}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Selfie ────────────────────────────────────────────────────────────────────

export async function requestSelfie(
  companion_id: string,
  user_id: string,
  scene?: string,
): Promise<string> {
  const res = await apiFetch(`${BASE}/selfie`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ companion_id, user_id, ...(scene ? { scene } : {}) }),
  });
  if (!res.ok) throw new Error(await res.text());
  return URL.createObjectURL(await res.blob());
}

// ── Chat history ───────────────────────────────────────────────────────────────

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export async function getChatHistory(
  companionId: string,
  limit: number = 20,
): Promise<HistoryMessage[]> {
  try {
    const params = new URLSearchParams({ companion_id: companionId, limit: String(limit) });
    const res = await apiFetch(`${BASE}/chat/history?${params}`);
    if (!res.ok) return [];
    const data = await res.json() as { messages?: HistoryMessage[] };
    return data.messages ?? [];
  } catch {
    return [];
  }
}

// ── Activities ────────────────────────────────────────────────────────────────

export async function startActivity(
  companion_id: string,
  user_id: string,
  activity_type: ActivityType,
): Promise<ActivityData> {
  const res = await apiFetch(`${BASE}/activity`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ companion_id, user_id, activity_type }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveActivityResult(
  user_id: string,
  companion_id: string,
  activity_type: string,
  result: "won" | "lost" | "completed",
): Promise<void> {
  await apiFetch(`${BASE}/activity/result`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id, companion_id, activity_type, result }),
  }).catch(() => {});
}

export async function getSubscriptionStatus(): Promise<{
  tier: string;
  status: string;
  subscribedAt: string | null;
  billingPeriod: string;
  accessExpiresAt: string | null;
}> {
  try {
    const resp = await apiFetch(`${BASE}/subscription-status`);
    if (!resp.ok) return { tier: "free", status: "inactive", subscribedAt: null, billingPeriod: "monthly", accessExpiresAt: null };
    const data = await resp.json();
    return {
      tier: data.tier ?? "free",
      status: data.status ?? "inactive",
      subscribedAt: data.subscribed_at ?? null,
      billingPeriod: data.billing_period ?? "monthly",
      accessExpiresAt: data.access_expires_at ?? null,
    };
  } catch {
    return { tier: "free", status: "inactive", subscribedAt: null, billingPeriod: "monthly", accessExpiresAt: null };
  }
}

export async function openBillingPortal(): Promise<{ url: string }> {
  const resp = await apiFetch(`${BASE}/billing-portal`, { method: "POST" });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function createCheckoutSession(plan: string): Promise<{ url: string }> {
  const resp = await apiFetch(`${BASE}/create-checkout-session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan }),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function submitWaitlist(
  email: string,
  companionId: string,
  userId?: string,
): Promise<void> {
  const resp = await fetch(`${BASE}/waitlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, companion_id: companionId, user_id: userId ?? null }),
  });
  if (!resp.ok) throw new Error("Waitlist submission failed");
}

// ── Milestones ─────────────────────────────────────────────────────────────────

export interface MilestoneState {
  id: string;
  title: string;
  description: string;
  icon: string;
  category: string;
  unlocked: boolean;
  unlocked_at: string | null;
  seen: boolean;
  progress: number;
  progress_max: number;
}

export interface MilestonesResponse {
  connection_score: number;
  bond_level: string;
  milestones: MilestoneState[];
  newly_unlocked: string[];
}

export async function getMilestones(companionId: string): Promise<MilestonesResponse> {
  const resp = await apiFetch(`${BASE}/milestones?companion_id=${encodeURIComponent(companionId)}`);
  if (!resp.ok) return { connection_score: 50, bond_level: "Warming", milestones: [], newly_unlocked: [] };
  return resp.json();
}

export async function markMilestonesSeen(companionId: string, milestoneIds: string[]): Promise<void> {
  if (!milestoneIds.length) return;
  await apiFetch(`${BASE}/milestones/seen`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ companion_id: companionId, milestone_ids: milestoneIds }),
  }).catch(() => {});
}

// ── Ritual ─────────────────────────────────────────────────────────────────────

export interface RitualStatus {
  due: boolean;
  questions: string[] | null;
}

export async function getRitualStatus(companionId: string): Promise<RitualStatus> {
  try {
    const resp = await apiFetch(`${BASE}/ritual/status?companion_id=${encodeURIComponent(companionId)}`);
    if (!resp.ok) return { due: false, questions: null };
    return resp.json();
  } catch {
    return { due: false, questions: null };
  }
}

// ── Daily question ─────────────────────────────────────────────────────────────

export interface DailyQuestion {
  question: string;
  type: "legacy" | "checkin";
  date: string;
}

export async function getPendingQuestion(): Promise<DailyQuestion | null> {
  try {
    const resp = await apiFetch(`${BASE}/notifications/pending-question`);
    if (!resp.ok) return null;
    return resp.json();
  } catch {
    return null;
  }
}
