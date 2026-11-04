from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from app.schemas.chat import Source, UserMessage
from app.schemas.common import UtcDatetime

ConversationId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9-]{8,64}$")]
ConfirmationId = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F-]{36}$")]


class AgentChatRequest(BaseModel):
    message: UserMessage
    conversation_id: ConversationId


class AgentAction(BaseModel):
    tool: str
    label: str
    ok: bool


class ConfirmationPrompt(BaseModel):
    id: str
    kind: Literal["refund_request", "support_ticket"]
    title: str
    details: list[str]
    expires_at: UtcDatetime


class AgentChatResponse(BaseModel):
    reply: str
    intent: str
    sources: list[Source] = []
    actions: list[AgentAction] = []
    confirmation: ConfirmationPrompt | None = None


class ConfirmRequest(BaseModel):
    confirmation_id: ConfirmationId
    decision: Literal["confirm", "cancel"]


class ConfirmResponse(BaseModel):
    outcome: Literal["created", "cancelled", "failed", "expired", "not_found", "already_resolved"]
    reply: str
    reference: str | None = None
    status: str | None = None