"""LangGraph nodes. At most two LLM calls per turn: classify (constrained JSON) and phrase the answer.

Tool arguments come from code (regex and validated enums), never from free-form model output.
The graph has no loops, so tool-calling cannot run away.
"""

import json
import re
from typing import Any

from pydantic import ValidationError
from app.agent.prompts import AGENT_SYSTEM_PROMPT, CLASSIFIER_PROMPT
from app.security import ai_safety, audit, pii
from app.agent.actions import prepare_refund_request, prepare_support_ticket

from app.security import ai_safety, audit, pii
from app.agent.prompts import AGENT_SYSTEM_PROMPT, CLASSIFIER_PROMPT
from app.agent.parsing import (
    heuristic_intent,
    parse_category,
    parse_order_number,
    parse_photos,
    parse_reason,
)
from app.agent.prompts import (
    GENERIC_FAILURE_REPLY,
    OFF_TOPIC_REPLY,
    build_classifier_messages,
    build_respond_messages,
    guard_claims,
)
from app.agent.state import CLASSIFICATION_SCHEMA, AgentState, Intent
from app.core.config import settings
from app.models import RefundReason, TicketCategory
from app.schemas.agent import AgentAction
from app.schemas.tools import (
    CheckRefundEligibilityInput,
    GetCustomerOrdersInput,
    GetOrderStatusInput,
    ToolError,
    ToolResult,
)
from app.services.llm_service import chat_completion
from app.services.retrieval_service import KnowledgeBaseEmptyError, retrieve
from app.tools import support_tools

ORDER_INTENTS = {Intent.ORDER_STATUS, Intent.REFUND_ELIGIBILITY, Intent.REFUND_REQUEST}
_CREATE_VERBS = re.compile(
    r"\b(submit|create|file|open|raise|start|make|send|lodge|request|want|need|would like|like to)\b", re.I
)
_TICKET_WORDS = re.compile(r"\b(ticket|complaint|escalat\w*)\b", re.I)

CLARIFY_QUESTIONS = {
    "order_number": "Which order is this about? Please give me the order number (for example SP-1004).",
    "reason": (
        "What is the reason for the refund? For example: the parcel arrived damaged, an Express parcel "
        "was late, the parcel was lost, the order was cancelled, or there was a billing error."
    ),
    "photos": (
        "How many clear photos of the damage can you provide? At least 2 are needed "
        "(the damaged item, and the outer packaging showing the shipping label)."
    ),
    "description": "Please describe the problem in a sentence or two so the support team can help.",
}


def _enum_or_none(enum_cls: Any, value: Any) -> Any:
    if not isinstance(value, str) or value == "none":
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return None


def _classify_with_llm(
    message: str, history: list[dict[str, str]]
) -> tuple[Intent, bool, RefundReason | None, TicketCategory | None, bool]:
    raw = chat_completion(
        build_classifier_messages(message, history), temperature=0, json_schema=CLASSIFICATION_SCHEMA
    )
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not an object")
        intent = Intent(data["intent"])
    except (ValueError, KeyError, TypeError):
        return heuristic_intent(message), False, None, None, False
    return (
        intent,
        bool(data.get("needs_policy")),
        _enum_or_none(RefundReason, data.get("refund_reason")),
        _enum_or_none(TicketCategory, data.get("ticket_category")),
        bool(data.get("has_problem_description")),
    )


def _sanity_check_intent(intent: Intent, message: str) -> Intent:
    """A question can never become a creation request."""
    if intent == Intent.REFUND_REQUEST and not (
        _CREATE_VERBS.search(message) and re.search(r"refund", message, re.I)
    ):
        return Intent.REFUND_ELIGIBILITY
    if intent == Intent.TICKET_REQUEST and not _TICKET_WORDS.search(message):
        return Intent.POLICY
    return intent


def _fill_awaiting(message: str, slots: dict[str, Any]) -> dict[str, Any] | None:
    """Deterministically fill the one slot we asked about. None means the user moved on."""
    awaiting = slots.get("awaiting")
    if not awaiting:
        return None
    updated = dict(slots)
    if awaiting == "order_number":
        value = parse_order_number(message)
        if value is None:
            return None
        updated["order_number"] = value
    elif awaiting == "reason":
        reason = parse_reason(message)
        if reason is None:
            return None
        updated["reason"] = reason.value
    elif awaiting == "photos":
        photos = parse_photos(message, allow_bare=True)
        if photos is None:
            return None
        updated["photos"] = photos
    elif awaiting == "description":
        text = message.strip()
        if len(text) < 10:
            return None
        updated["description"] = text
    else:
        return None
    updated["awaiting"] = None
    return updated


def classify_node(state: AgentState) -> dict[str, Any]:
    message = state["message"]
    filled = _fill_awaiting(message, state.get("slots") or {})

    if filled is not None:
        slots = filled
        intent = Intent(slots["intent"])
        needs_policy, llm_reason, llm_category, has_problem = False, None, None, False
    else:
        slots = {}
        intent, needs_policy, llm_reason, llm_category, has_problem = _classify_with_llm(
            message, state.get("history", [])
        )
        intent = _sanity_check_intent(intent, message)

    order_number = parse_order_number(message) or slots.get("order_number")
    if order_number is None and intent != Intent.TICKET_REQUEST:
        order_number = state.get("last_order_number")  # follow-ups like "can I get a refund for it?"

    reason = parse_reason(message)
    if reason is None and slots.get("reason"):
        reason = RefundReason(slots["reason"])
    if reason is None and intent == Intent.REFUND_ELIGIBILITY:
        reason = llm_reason  # creation requires an explicit, keyword-backed reason

    photos = parse_photos(message)
    if photos is None:
        photos = slots.get("photos")

    category = (
        TicketCategory(slots["category"]) if slots.get("category") else (llm_category or parse_category(message))
    )

    description = slots.get("description")
    if (
        intent == Intent.TICKET_REQUEST
        and description is None
        and has_problem
        and len(message.split()) >= 6
    ):
        description = message.strip()

    missing: str | None = None
    if intent == Intent.ORDER_STATUS and not order_number:
        missing = "order_number"
    elif intent == Intent.REFUND_ELIGIBILITY:
        missing = "order_number" if not order_number else ("reason" if reason is None else None)
    elif intent == Intent.REFUND_REQUEST:
        if not order_number:
            missing = "order_number"
        elif reason is None:
            missing = "reason"
        elif reason == RefundReason.DAMAGED and photos is None:
            missing = "photos"
    elif intent == Intent.TICKET_REQUEST and not description:
        missing = "description"

    carry = {
        "intent": intent.value,
        "order_number": order_number,
        "reason": reason.value if reason else None,
        "photos": photos,
        "category": category.value if category else None,
        "description": description,
    }
    return {
        "intent": intent.value,
        "needs_policy": needs_policy,
        "order_number": order_number,
        "reason": reason,
        "photos": photos,
        "category": category,
        "description": description,
        "missing": missing,
        "carry": carry,
    }


def clarify_node(state: AgentState) -> dict[str, Any]:
    missing = state["missing"]
    return {
        "reply": CLARIFY_QUESTIONS[missing],
        "next_slots": {**state["carry"], "awaiting": missing},
    }


def _record(state: AgentState, tool: str, label: str, result: ToolResult) -> dict[str, Any]:
    results = list(state.get("tool_results", []))
    results.append(
        {
            "tool": tool,
            "ok": result.ok,
            "data": result.data.model_dump(mode="json") if result.data else None,
            "error": result.error.model_dump() if result.error else None,
        }
    )
    actions = list(state.get("actions", []))
    actions.append(AgentAction(tool=tool, label=label if result.ok else f"{label} (failed)", ok=result.ok))
    return {"tool_results": results, "actions": actions}


def run_order_tool_node(state: AgentState) -> dict[str, Any]:
    ctx = state["ctx"]
    intent = state["intent"]
    order_number = state.get("order_number")
    try:
        if intent == Intent.ORDER_STATUS:
            tool, label = "get_order_status", "Checked order status"
            result = support_tools.get_order_status(ctx, GetOrderStatusInput(order_number=order_number))
        elif intent == Intent.LIST_ORDERS:
            tool, label = "get_customer_orders", "Looked up your orders"
            result = support_tools.get_customer_orders(ctx, GetCustomerOrdersInput(limit=10))
        else:
            tool, label = "check_refund_eligibility", "Checked refund eligibility"
            result = support_tools.check_refund_eligibility(
                ctx,
                CheckRefundEligibilityInput(
                    order_number=order_number,
                    reason=state["reason"],
                    evidence_photo_count=state.get("photos") or 0,
                ),
            )
    except ValidationError:
        result = ToolResult(
            ok=False, error=ToolError(code="INVALID_INPUT", message="The order number or details were not valid.")
        )

    update = _record(state, tool, label, result)
    if result.ok and order_number and intent != Intent.LIST_ORDERS:
        update["verified_order"] = order_number
    return update


def retrieve_policy_node(state: AgentState) -> dict[str, Any]:
    ctx = state["ctx"]
    try:
        retrieved = retrieve(pii.mask_pii(state["message"]))
        error = False
    except KnowledgeBaseEmptyError:
        retrieved, error = [], True

    # Retrieved text is untrusted: quarantine instruction-like chunks, and delimit the rest as data.
    chunks, quarantined = ai_safety.screen_chunks(retrieved)
    for chunk_id in quarantined:
        audit.record("rag.chunk_quarantined", "rejected", principal=ctx.principal,
                     resource_type="policy_chunk", resource_id=chunk_id,
                     detail="instruction_like_content", channel=ctx.channel)

    actions = list(state.get("actions", []))
    actions.append(
        AgentAction(
            tool="search_policies",
            label="Searched company policies" if not error else "Searched company policies (failed)",
            ok=not error,
        )
    )
    return {"chunks": chunks, "policy_error": error, "actions": actions}


def describe_failure(result: ToolResult) -> str:
    error = result.error
    if error is None:
        return GENERIC_FAILURE_REPLY
    if error.code == "ORDER_NOT_FOUND":
        return "I couldn't find that order on your account. Please check the order number and try again."
    if error.code == "NOT_ELIGIBLE":
        eligibility = getattr(result.data, "eligibility", None)
        extra = f" {eligibility.next_action}" if eligibility else ""
        return f"I can't submit that request. {error.message}{extra}"
    return f"I can't submit that request. {error.message}"


def prepare_action_node(state: AgentState) -> dict[str, Any]:
    """Prepares a confirmation card. Never creates anything."""
    ctx = state["ctx"]
    actions = list(state.get("actions", []))

    if state["intent"] == Intent.REFUND_REQUEST:
        tool, noun = "create_refund_request", "refund request"
        prompt, result = prepare_refund_request(
            ctx, order_number=state["order_number"], reason=state["reason"], photos=state.get("photos") or 0
        )
        intro = ""
        if prompt and result.data and result.data.eligibility:
            intro = result.data.eligibility.reason + "\n\n"
    else:
        tool, noun = "create_support_ticket", "support ticket"
        prompt, result = prepare_support_ticket(
            ctx,
            order_number=state.get("order_number"),
            category=state.get("category") or TicketCategory.OTHER,
            description=state["description"],
        )
        intro = ""

    if prompt is None:
        actions.append(AgentAction(tool=tool, label=f"Could not prepare {noun}", ok=False))
        return {"reply": describe_failure(result), "actions": actions, "confirmation": None}

    actions.append(AgentAction(tool=tool, label=f"Prepared {noun} (awaiting your confirmation)", ok=True))
    reply = f"{intro}Please review the details below. Nothing has been created yet; I'll only go ahead if you confirm."
    update: dict[str, Any] = {"reply": reply, "actions": actions, "confirmation": prompt}
    if state.get("order_number"):
        update["verified_order"] = state["order_number"]
    return update

def respond_node(state: AgentState) -> dict[str, Any]:
    if state["intent"] == Intent.OFF_TOPIC:
        return {"reply": OFF_TOPIC_REPLY}
    messages = build_respond_messages(
        history=state.get("history", []),
        message=state["message"],
        tool_results=state.get("tool_results", []),
        chunks=state.get("chunks"),
        policy_error=state.get("policy_error", False),
    )
    reply = chat_completion(messages, temperature=settings.ollama_temperature).strip()
    if not reply:
        return {"reply": GENERIC_FAILURE_REPLY}
    safe = ai_safety.filter_reply(reply, [AGENT_SYSTEM_PROMPT, CLASSIFIER_PROMPT])
    return {"reply": guard_claims(safe)}

def route_after_classify(state: AgentState) -> str:
    if state.get("missing"):
        return "clarify"
    intent = state["intent"]
    if intent == Intent.POLICY:
        return "retrieve_policy"
    if intent in (Intent.ORDER_STATUS, Intent.LIST_ORDERS, Intent.REFUND_ELIGIBILITY):
        return "run_order_tool"
    if intent in (Intent.REFUND_REQUEST, Intent.TICKET_REQUEST):
        return "prepare_action"
    return "respond"


def route_after_tool(state: AgentState) -> str:
    return "retrieve_policy" if state.get("needs_policy") else "respond"