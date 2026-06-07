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
}

export interface ChatResponse {
  session_id: string;
  persona_id: string;
  reply: string;
  message_count: number;
  model_backend: "claude" | "venice";
}

// ── Personas ──────────────────────────────────────────────────────────────────

export async function createPersona(data: {
  name: string;
  relationship_type: string;
  personality_traits: string[];
  backstory?: string;
  custom_relationship?: string;
  voice_id?: string | null;
  nsfw_mode?: boolean;
}): Promise<Persona> {
  const res = await fetch(`${BASE}/personas`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listPersonas(): Promise<Persona[]> {
  const res = await fetch(`${BASE}/personas`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Chat (streaming) ──────────────────────────────────────────────────────────

export interface StreamEvent {
  type: "token" | "done" | "error";
  text?: string;
  full_text?: string;
  message_count?: number;
  model_backend?: "claude" | "venice";
  message?: string;
}

export async function* chatStream(
  session_id: string,
  persona_id: string,
  message: string,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id, persona_id, message }),
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
      try {
        yield JSON.parse(line.slice(6)) as StreamEvent;
      } catch {}
    }
  }
}

// ── Memories ──────────────────────────────────────────────────────────────────

export interface Memory {
  id: string;
  content: string;
  created_at: string;
}

export interface MemoriesResponse {
  user_id: string;
  persona_id: string;
  memories: Memory[];
  count: number;
}

export async function fetchMemories(
  user_id: string,
  persona_id: string,
): Promise<MemoriesResponse> {
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
  const data = await res.json();
  return data.transcript as string;
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
}

export interface ProactiveMessagesResponse {
  user_id: string;
  companion_id: string;
  messages: ProactiveMessage[];
  count: number;
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

/**
 * Request an AI-generated selfie from a companion.
 * Returns a blob URL pointing to the image (valid for this browser session).
 */
export async function requestSelfie(
  companion_id: string,
  user_id: string,
): Promise<string> {
  const res = await fetch(`${BASE}/selfie`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ companion_id, user_id }),
  });
  if (!res.ok) throw new Error(await res.text());
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}
