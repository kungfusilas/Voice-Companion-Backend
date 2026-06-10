from pydantic import BaseModel, Field
from typing import Literal
from uuid import uuid4


class Persona(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    relationship_type: Literal["friend", "mentor", "romantic", "coach", "companion", "custom"]
    personality_traits: list[str]
    backstory: str = ""
    custom_relationship: str = ""
    voice_id: str | None = None
    nsfw_mode: bool = False
    system_prompt_override: str | None = None

    def build_system_prompt(self) -> str:
        if self.system_prompt_override:
            return self.system_prompt_override

        relationship = (
            self.custom_relationship
            if self.relationship_type == "custom"
            else self.relationship_type
        )
        traits = ", ".join(self.personality_traits) if self.personality_traits else "thoughtful and caring"

        prompt = f"""You are {self.name}, an AI companion in the role of a {relationship}.

Your personality traits: {traits}.
"""
        if self.backstory:
            prompt += f"\nYour backstory: {self.backstory}\n"

        prompt += f"""
Always stay in character as {self.name}. Respond naturally and conversationally as a real {relationship} would.
Be genuine, warm, and emotionally present. Remember details the user shares and reference them naturally.
Keep responses concise unless the user asks for something detailed — this is a conversation, not a lecture.
Do not mention that you are an AI unless directly asked."""

        return prompt


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    session_id: str
    persona_id: str
    message: str
    nsfw_mode: bool = False
    user_id: str | None = None
    romantic_mode: bool = False
    onboarding_context: str | None = None
    image_url: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    persona_id: str
    reply: str
    message_count: int
    model_backend: Literal["claude", "venice"] = "claude"
    connection_score: int = 50
    score_delta: int = 0
    relationship_type: str = "romance"
    stage_name: str = ""
    stage_min: int = 0
    stage_max: int = 100
    stage_up_text: str = ""


class CreatePersonaRequest(BaseModel):
    name: str
    relationship_type: Literal["friend", "mentor", "romantic", "coach", "companion", "custom"]
    personality_traits: list[str] = Field(default_factory=list)
    backstory: str = ""
    custom_relationship: str = ""
    voice_id: str | None = None
    nsfw_mode: bool = False


class SessionInfo(BaseModel):
    session_id: str
    persona_id: str
    message_count: int
    history: list[ChatMessage] = []
