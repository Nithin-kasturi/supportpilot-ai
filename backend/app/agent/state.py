from enum import StrEnum
from typing import Any, TypedDict

from app.models import RefundReason, TicketCategory
from app.schemas.agent import AgentAction, ConfirmationPrompt
from app.services.retrieval_service import RetrievedChunk
from app.tools.support_tools import ToolContext


class Intent(StrEnum):
    CHITCHAT = "greeting_or_chitchat"
    POLICY = "policy_question"
    ORDER_STATUS = "order_status"
    LIST_ORDERS = "list_orders"
    REFUND_ELIGIBILITY = "refund_eligibility"
    REFUND_REQUEST = "refund_request"
    TICKET_REQUEST = "ticket_request"
    OFF_TOPIC = "off_topic"


# Plain inline enums (no $ref/$defs) so Ollama's schema-to-grammar conversion handles it reliably.
CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [i.value for i in Intent]},
        "needs_policy": {"type": "boolean"},
        "refund_reason": {"type": "string", "enum": ["none", *[r.value for r in RefundReason]]},
        "ticket_category": {"type": "string", "enum": ["none", *[c.value for c in TicketCategory]]},
        "has_problem_description": {"type": "boolean"},
    },
    "required": [
        "intent",
        "needs_policy",
        "refund_reason",
        "ticket_category",
        "has_problem_description",
    ],
}


class AgentState(TypedDict, total=False):
    # Inputs (set by the caller)
    ctx: ToolContext
    message: str
    history: list[dict[str, str]]
    last_order_number: str | None
    slots: dict[str, Any]
    # Classification and resolved entities
    intent: str
    needs_policy: bool
    order_number: str | None
    reason: RefundReason | None
    photos: int | None
    category: TicketCategory | None
    description: str | None
    missing: str | None
    carry: dict[str, Any]
    # Gathered data
    tool_results: list[dict[str, Any]]
    actions: list[AgentAction]
    chunks: list[RetrievedChunk] | None
    policy_error: bool
    verified_order: str | None
    # Outputs
    reply: str
    confirmation: ConfirmationPrompt | None
    next_slots: dict[str, Any]