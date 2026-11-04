"""Backend support tools: typed, customer-scoped, structured results.

These are the only entry points an AI agent will be allowed to use (Milestone 4). Customer identity
comes from ToolContext, which the backend builds, never from tool parameters or model output.
"""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Customer, RefundRequest, SupportTicket
from app.schemas.orders import TrackingOut
from app.schemas.refunds import EligibilityResult
from app.schemas.tools import (
    CheckRefundEligibilityInput,
    CreateRefundOutput,
    CreateRefundRequestInput,
    CreateSupportTicketInput,
    CreateTicketOutput,
    CustomerOrdersOutput,
    GetCustomerOrdersInput,
    GetOrderStatusInput,
    TicketPreview,
    ToolError,
    ToolResult,
)
from app.services import order_service, refund_service, ticket_service
from app.services.order_service import OrderNotFoundError
from app.services.refund_eligibility_service import check_eligibility


@dataclass(frozen=True)
class ToolContext:
    """Trusted and backend-supplied. Never construct from request bodies, chat text or LLM output."""

    db: Session
    customer: Customer


def _ok(output_type, data):
    return ToolResult[output_type](ok=True, data=data)


def _fail(output_type, code: str, message: str, data=None):
    return ToolResult[output_type](ok=False, error=ToolError(code=code, message=message), data=data)


def get_order_status(ctx: ToolContext, params: GetOrderStatusInput) -> ToolResult[TrackingOut]:
    try:
        order = order_service.get_order(ctx.db, ctx.customer.id, params.order_number)
    except OrderNotFoundError:
        return _fail(TrackingOut, "ORDER_NOT_FOUND", "Order not found.")
    return _ok(TrackingOut, order_service.build_tracking(order))


def get_customer_orders(
    ctx: ToolContext, params: GetCustomerOrdersInput
) -> ToolResult[CustomerOrdersOutput]:
    orders = order_service.list_orders(ctx.db, ctx.customer.id, params.status)[: params.limit]
    output = CustomerOrdersOutput(count=len(orders), orders=[order_service.to_summary(o) for o in orders])
    return _ok(CustomerOrdersOutput, output)


def check_refund_eligibility(
    ctx: ToolContext, params: CheckRefundEligibilityInput
) -> ToolResult[EligibilityResult]:
    try:
        order = order_service.get_order(ctx.db, ctx.customer.id, params.order_number)
    except OrderNotFoundError:
        return _fail(EligibilityResult, "ORDER_NOT_FOUND", "Order not found.")
    return _ok(EligibilityResult, check_eligibility(order, params.reason, params.evidence_photo_count))


def _duplicate_refund(existing: RefundRequest) -> ToolResult[CreateRefundOutput]:
    return _fail(
        CreateRefundOutput,
        "DUPLICATE_REQUEST",
        f"A refund request ({existing.reference}) already exists for this order.",
        CreateRefundOutput(outcome="not_created", refund_request=refund_service.to_out(existing)),
    )


def create_refund_request(
    ctx: ToolContext, params: CreateRefundRequestInput
) -> ToolResult[CreateRefundOutput]:
    """Order of checks: ownership, duplicates, eligibility (re-run here), then confirmation."""
    try:
        order = order_service.get_order(ctx.db, ctx.customer.id, params.order_number)
    except OrderNotFoundError:
        return _fail(CreateRefundOutput, "ORDER_NOT_FOUND", "Order not found.")

    existing = refund_service.find_active_request(ctx.db, order.id)
    if existing is not None:
        return _duplicate_refund(existing)

    result = check_eligibility(order, params.reason, params.evidence_photo_count)

    if result.eligible is False:
        return _fail(
            CreateRefundOutput, "NOT_ELIGIBLE", result.reason,
            CreateRefundOutput(outcome="not_created", eligibility=result),
        )
    if result.eligible is None:
        return _fail(
            CreateRefundOutput, "MANUAL_REVIEW_REQUIRED", f"{result.reason} {result.next_action}",
            CreateRefundOutput(outcome="not_created", eligibility=result),
        )

    status = refund_service.status_for(result)
    if not params.confirmed:
        return _ok(
            CreateRefundOutput,
            CreateRefundOutput(outcome="confirmation_required", eligibility=result, status_if_created=status),
        )

    try:
        request = refund_service.create_refund_request(
            ctx.db,
            order=order,
            customer_id=ctx.customer.id,
            result=result,
            evidence_photo_count=params.evidence_photo_count,
            note=params.customer_note,
        )
        ctx.db.commit()
    except IntegrityError:
        ctx.db.rollback()
        existing = refund_service.find_active_request(ctx.db, order.id)
        if existing is not None:
            return _duplicate_refund(existing)
        raise

    return _ok(
        CreateRefundOutput,
        CreateRefundOutput(
            outcome="created",
            eligibility=result,
            status_if_created=status,
            refund_request=refund_service.to_out(request),
        ),
    )


def _duplicate_ticket(existing: SupportTicket) -> ToolResult[CreateTicketOutput]:
    return _fail(
        CreateTicketOutput,
        "DUPLICATE_TICKET",
        f"An open {existing.category.value.replace('_', ' ')} ticket ({existing.reference}) already exists for this order.",
        CreateTicketOutput(outcome="not_created", ticket=ticket_service.to_out(existing)),
    )


def create_support_ticket(
    ctx: ToolContext, params: CreateSupportTicketInput
) -> ToolResult[CreateTicketOutput]:
    """Order of checks: ownership, duplicates, then confirmation. Records only; nothing is executed."""
    order = None
    if params.order_number is not None:
        try:
            order = order_service.get_order(ctx.db, ctx.customer.id, params.order_number)
        except OrderNotFoundError:
            return _fail(CreateTicketOutput, "ORDER_NOT_FOUND", "Order not found.")
        existing = ticket_service.find_open_ticket(ctx.db, ctx.customer.id, order.id, params.category)
        if existing is not None:
            return _duplicate_ticket(existing)

    if not params.confirmed:
        preview = TicketPreview(
            order_number=order.order_number if order else None,
            category=params.category,
            subject=params.subject,
            description=params.description,
        )
        return _ok(CreateTicketOutput, CreateTicketOutput(outcome="confirmation_required", preview=preview))

    try:
        ticket = ticket_service.create_ticket(
            ctx.db,
            customer_id=ctx.customer.id,
            order=order,
            category=params.category,
            subject=params.subject,
            description=params.description,
        )
        ctx.db.commit()
    except IntegrityError:
        ctx.db.rollback()
        if order is not None:
            existing = ticket_service.find_open_ticket(ctx.db, ctx.customer.id, order.id, params.category)
            if existing is not None:
                return _duplicate_ticket(existing)
        raise

    return _ok(
        CreateTicketOutput,
        CreateTicketOutput(outcome="created", ticket=ticket_service.to_out(ticket)),
    )