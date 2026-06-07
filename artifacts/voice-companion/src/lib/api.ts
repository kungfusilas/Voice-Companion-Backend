const BASE = "/companion/api";

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
  const res = await fetch(`${BASE}/personas`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Relationship ──────────────────────────────────────────────────────────────

export async function getRelationshipStats(
  userId: string,
  companionId: string,
): Promise<RelationshipStats> {
  const res = await fetch(`${BASE}/relationship/${userId}/${companionId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function setRelationshipType(
  userId: string,
  companionId: string,
  relType: string,
): Promise<void> {
  const res = await fetch(`${BASE}/relationship/type`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, companion_id: companionId, relationship_type: relType }),
  });
  if (!res.ok) throw new Error(await res.text());
}

// ── Chat (streaming) ──────────────────────────────────────────────────────────

export interface StreamEvent {
  type: "token" | "done" | "error" | "searching";
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
}

export async function* chatStream(
  session_id: string,
  persona_id: string,
  message: string,
  user_id?: string,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id, persona_id, message, user_id }),
  });
  if (!res.ok || !res.body) throw new Error(await res.text());

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

// ── Memories ──────────────────────────────────────────────────────────────────

export interface Memory { id: string; content: string; created_at: string; }
export interface MemoriesResponse {
  user_id: string; persona_id: string; memories: Memory[]; count: number;
}

export async function fetchMemories(user_id: string, persona_id: string): Promise<MemoriesResponse> {
  const params = new URLSearchParams({ user_id, persona_id });
  const res = await fetch(`${BASE}/memories?${params}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── STT ───────────────────────────────────────────────────────────────────────

export async function transcribeAudio(blob: Blob): Promise<string> {
  const form = new FormData();
  form.append("audio", blob, "recording.webm");
  const res = await fetch(`${BASE}/stt`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()).transcript as string;
}

// ── TTS ───────────────────────────────────────────────────────────────────────

export async function speakText(text: string, persona_id: string): Promise<Blob> {
  const res = await fetch(`${BASE}/tts/speak`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, persona_id }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.blob();
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
  const res = await fetch(`${BASE}/proactive-messages/${user_id}/${companion_id}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Selfie ────────────────────────────────────────────────────────────────────

export async function requestSelfie(companion_id: string, user_id: string): Promise<string> {
  const res = await fetch(`${BASE}/selfie`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ companion_id, user_id }),
  });
  if (!res.ok) throw new Error(await res.text());
  return URL.createObjectURL(await res.blob());
}

// ── Activities ────────────────────────────────────────────────────────────────

export async function startActivity(
  companion_id: string,
  user_id: string,
  activity_type: ActivityType,
): Promise<ActivityData> {
  const res = await fetch(`${BASE}/activity`, {
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
  await fetch(`${BASE}/activity/result`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id, companion_id, activity_type, result }),
  }).catch(() => {});
}

// ── Helpers ───────────────────────────────────────────────────────────────────

export function getOrCreateUserId(): string {
  const key = "vc_user_id";
  let id = localStorage.getItem(key);
  if (!id) {
    id = `u_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
    localStorage.setItem(key, id);
  }
  return id;
}
