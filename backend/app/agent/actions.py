"""Sensitive operations: prepare (preview + pending action) and resolve (customer decision).

Nothing is created here without a stored, owned, unexpired, single-use pending action and an explicit
customer decision. Execution re-runs the tools, which re-check permission, ownership and eligibility.
"""

import json

from pydantic import ValidationError

from app.database.session import utcnow
from app.models import (
    PendingActionStatus,
    PendingActionType,
    RefundReason,
    RefundStatus,
    TicketCategory,
)
from app.schemas.agent import ConfirmationPrompt, ConfirmResponse
from app.schemas.tools import (
    CreateRefundOutput,
    CreateRefundRequestInput,
    CreateSupportTicketInput,
    CreateTicketOutput,
    ToolError,
    ToolResult,
)
from app.security import audit
from app.services import pending_action_service as pending
from app.services.refund_eligibility_service import usd
from app.tools import support_tools
from app.tools.support_tools import ToolContext

REFUND_STATUS_TEXT = {
    RefundStatus.APPROVED: "Approved automatically",
    RefundStatus.PENDING_REVIEW: "Pending support review",
    RefundStatus.REJECTED: "Rejected",
}
REASON_TEXT = {
    RefundReason.DAMAGED: "Parcel arrived damaged",
    RefundReason.LATE_EXPRESS: "Express parcel delivered late",
    RefundReason.LOST: "Parcel lost",
    RefundReason.CANCELLED: "Order cancelled",
    RefundReason.BILLING_ERROR: "Billing error",
    RefundReason.OTHER: "Other",
}
CATEGORY_TEXT = {
    TicketCategory.DELIVERY_ISSUE: "Delivery issue",
    TicketCategory.DAMAGED_PARCEL: "Damaged parcel",
    TicketCategory.REFUND: "Refund",
    TicketCategory.CANCELLATION: "Cancellation",
    TicketCategory.COMPLAINT: "Complaint",
    TicketCategory.OTHER: "Other",
}


def _invalid(message: str = "The details provided were not valid.") -> ToolResult:
    return ToolResult(ok=False, error=ToolError(code="INVALID_INPUT", message=message))


def prepare_refund_request(
    ctx: ToolContext, *, order_number: str, reason: RefundReason, photos: int, note: str | None = None
) -> tuple[ConfirmationPrompt | None, ToolResult]:
    try:
        params = CreateRefundRequestInput(
            order_number=order_number, reason=reason, evidence_photo_count=photos,
            customer_note=note, confirmed=False,
        )
    except ValidationError:
        return None, _invalid()

    result = support_tools.create_refund_request(ctx, params)
    data = result.data
    if not (result.ok and data and data.outcome == "confirmation_required" and data.eligibility):
        return None, result

    action = pending.create_pending(
        ctx.db, ctx.customer.id, PendingActionType.REFUND_REQUEST,
        params.model_dump(mode="json", exclude={"confirmed"}),
    )
    audit.record("refund.prepare", "success", principal=ctx.principal, resource_type="order",
                 resource_id=params.order_number, detail="confirmation_requested", channel=ctx.channel)
    eligibility = data.eligibility
    status_text = REFUND_STATUS_TEXT[data.status_if_created] if data.status_if_created else "Pending"
    prompt = ConfirmationPrompt(
        id=action.id,
        kind="refund_request",
        title=f"Submit a refund request for {params.order_number}?",
        details=[
            f"Order: {params.order_number}",
            f"Reason: {REASON_TEXT[reason]}",
            f"Refundable amount: {usd(eligibility.refundable_amount_cents or 0)}",
            f"Resulting status: {status_text}",
            "This only records a request. No refund is executed and no money is moved.",
        ],
        expires_at=action.expires_at,
    )
    return prompt, result


def prepare_support_ticket(
    ctx: ToolContext, *, order_number: str | None, category: TicketCategory, description: str
) -> tuple[ConfirmationPrompt | None, ToolResult]:
    subject = (
        f"{CATEGORY_TEXT[category]} - order {order_number}"
        if order_number
        else f"{CATEGORY_TEXT[category]} - general request"
    )
    try:
        params = CreateSupportTicketInput(
            order_number=order_number, category=category, subject=subject,
            description=description, confirmed=False,
        )
    except ValidationError:
        return None, _invalid("Please describe the problem in at least a sentence (10 to 2000 characters).")

    result = support_tools.create_support_ticket(ctx, params)
    data = result.data
    if not (result.ok and data and data.outcome == "confirmation_required" and data.preview):
        return None, result

    action = pending.create_pending(
        ctx.db, ctx.customer.id, PendingActionType.SUPPORT_TICKET,
        params.model_dump(mode="json", exclude={"confirmed"}),
    )
    audit.record("ticket.prepare", "success", principal=ctx.principal, resource_type="order",
                 resource_id=order_number, detail="confirmation_requested", channel=ctx.channel)
    preview = data.preview
    prompt = ConfirmationPrompt(
        id=action.id,
        kind="support_ticket",
        title="Create a support ticket?",
        details=[
            f"Category: {CATEGORY_TEXT[preview.category]}",
            f"Order: {preview.order_number or 'none (general request)'}",
            f"Subject: {preview.subject}",
            f"Description: {preview.description[:200]}",
        ],
        expires_at=action.expires_at,
    )
    return prompt, result


def _audit_resolution(ctx: ToolContext, action_id: str, outcome: str, detail: str) -> None:
    audit.record("confirmation.resolve", outcome, principal=ctx.principal,
                 resource_type="pending_action", resource_id=action_id, detail=detail, channel=ctx.channel)


def _failed(ctx: ToolContext, action_id: str, reply: str) -> ConfirmResponse:
    pending.set_status(ctx.db, action_id, PendingActionStatus.FAILED)
    return ConfirmResponse(outcome="failed", reply=reply)


def _execute(ctx: ToolContext, action_id: str, action_type: PendingActionType, params: dict) -> ConfirmResponse:
    try:
        if action_type == PendingActionType.REFUND_REQUEST:
            result: ToolResult[CreateRefundOutput] = support_tools.create_refund_request(
                ctx, CreateRefundRequestInput(**params, confirmed=True)
            )
            if result.ok and result.data and result.data.outcome == "created" and result.data.refund_request:
                record = result.data.refund_request
                return ConfirmResponse(
                    outcome="created", reference=record.reference, status=record.status.value,
                    reply=(
                        f"Done. Refund request {record.reference} was submitted for "
                        f"{usd(record.amount_cents)}. Status: {REFUND_STATUS_TEXT[record.status]}. "
                        "This records the request only; no money has been moved."
                    ),
                )
        else:
            ticket_result: ToolResult[CreateTicketOutput] = support_tools.create_support_ticket(
                ctx, CreateSupportTicketInput(**params, confirmed=True)
            )
            if (ticket_result.ok and ticket_result.data and ticket_result.data.outcome == "created"
                    and ticket_result.data.ticket):
                ticket = ticket_result.data.ticket
                return ConfirmResponse(
                    outcome="created", reference=ticket.reference, status=ticket.status.value,
                    reply=f"Done. Support ticket {ticket.reference} was created (status: {ticket.status.value}). The support team will follow up.",
                )
            result = ticket_result  # type: ignore[assignment]
    except ValidationError:
        return _failed(ctx, action_id, "I couldn't complete that request because its details were no longer valid.")

    message = result.error.message if result.error else "The operation could not be completed."
    return _failed(ctx, action_id, f"I couldn't complete that: {message} Nothing was created.")


def resolve_pending(ctx: ToolContext, action_id: str, decision: str) -> ConfirmResponse:
    action = pending.get_owned(ctx.db, ctx.customer.id, action_id)
    if action is None:
        _audit_resolution(ctx, action_id, "rejected", "not_found_or_not_owner")
        return ConfirmResponse(
            outcome="not_found", reply="I couldn't find that confirmation request, so nothing was created."
        )
    if action.status != PendingActionStatus.PENDING:
        _audit_resolution(ctx, action_id, "rejected", f"reuse_{action.status.value}")
        return ConfirmResponse(
            outcome="already_resolved",
            reply=f"That request was already {action.status.value}, so nothing further was done.",
        )
    if utcnow() > action.expires_at:
        pending.claim(ctx.db, action.id, PendingActionStatus.EXPIRED)
        _audit_resolution(ctx, action_id, "rejected", "expired")
        return ConfirmResponse(
            outcome="expired",
            reply="That confirmation has expired, so nothing was created. Ask me again if you still want to go ahead.",
        )

    if decision == "cancel":
        if pending.claim(ctx.db, action.id, PendingActionStatus.CANCELLED):
            _audit_resolution(ctx, action_id, "success", "cancelled")
            return ConfirmResponse(outcome="cancelled", reply="Okay, I won't go ahead. Nothing was created.")
        return ConfirmResponse(outcome="already_resolved", reply="That request was already resolved.")

    # Single use: only the caller that wins this atomic claim may execute.
    if not pending.claim(ctx.db, action.id, PendingActionStatus.CONFIRMED):
        _audit_resolution(ctx, action_id, "rejected", "reuse_race")
        return ConfirmResponse(outcome="already_resolved", reply="That request was already resolved.")
    _audit_resolution(ctx, action_id, "success", "confirmed")
    return _execute(ctx, action.id, action.action_type, json.loads(action.params_json))