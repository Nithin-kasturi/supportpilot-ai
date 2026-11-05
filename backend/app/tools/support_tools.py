"""Backend support tools: typed, permission-checked, customer-scoped, audited, structured results.

These are the only entry points the API, the LangGraph agent and the MCP server use for customer
operations. Identity comes from ToolContext (built by the backend from a validated token), never
from tool parameters or model output.
"""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Customer, Order, RefundRequest, SupportTicket
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
from app.security import audit
from app.security.permissions import Permission, has_permission
from app.security.principal import Principal
from app.services import order_service, refund_service, ticket_service
from app.services.order_service import OrderNotFoundError
from app.services.refund_eligibility_service import check_eligibility


@dataclass(frozen=True)
class ToolContext:
    """Trusted and backend-supplied. Never construct from request bodies, chat text or LLM output."""

    db: Session
    customer: Customer
    principal: Principal
    channel: str = "api"  # api | agent | mcp

    def __post_init__(self) -> None:
        if self.principal.customer_id != self.customer.id:
            raise PermissionError("Principal and customer do not match.")


def _ok(output_type, data):
    return ToolResult[output_type](ok=True, data=data)


def _fail(output_type, code: str, message: str, data=None):
    return ToolResult[output_type](ok=False, error=ToolError(code=code, message=message), data=data)


def _allowed(ctx: ToolContext, permission: Permission) -> bool:
    return has_permission(ctx.principal.role, permission)


def _forbidden(ctx: ToolContext, permission: Permission, output_type):
    audit.record(
        "authz.denied",
        "denied",
        principal=ctx.principal,
        resource_type="permission",
        resource_id=permission.value,
        channel=ctx.channel,
    )
    return _fail(output_type, "FORBIDDEN", "You do not have permission to use this tool.")


def _owned_order(ctx: ToolContext, order_number: str) -> Order | None:
    """Ownership is part of the query. A miss looks identical whether the order is missing or foreign."""
    try:
        return order_service.get_order(ctx.db, ctx.customer.id, order_number)
    except OrderNotFoundError:
        audit.record_denied_lookup(ctx.principal, "order", order_number.strip().upper(), ctx.channel)
        return None


def get_order_status(ctx: ToolContext, params: GetOrderStatusInput) -> ToolResult[TrackingOut]:
    if not _allowed(ctx, Permission.ORDERS_READ_OWN):
        return _forbidden(ctx, Permission.ORDERS_READ_OWN, TrackingOut)
    order = _owned_order(ctx, params.order_number)
    if order is None:
        return _fail(TrackingOut, "ORDER_NOT_FOUND", "Order not found.")
    audit.record("order.view", "success", principal=ctx.principal, resource_type="order",
                 resource_id=order.order_number, channel=ctx.channel)
    return _ok(TrackingOut, order_service.build_tracking(order))


def get_customer_orders(
    ctx: ToolContext, params: GetCustomerOrdersInput
) -> ToolResult[CustomerOrdersOutput]:
    if not _allowed(ctx, Permission.ORDERS_READ_OWN):
        return _forbidden(ctx, Permission.ORDERS_READ_OWN, CustomerOrdersOutput)
    orders = order_service.list_orders(ctx.db, ctx.customer.id, params.status)[: params.limit]
    audit.record("order.list", "success", principal=ctx.principal, resource_type="order",
                 detail=f"count={len(orders)}", channel=ctx.channel)
    output = CustomerOrdersOutput(count=len(orders), orders=[order_service.to_summary(o) for o in orders])
    return _ok(CustomerOrdersOutput, output)


def check_refund_eligibility(
    ctx: ToolContext, params: CheckRefundEligibilityInput
) -> ToolResult[EligibilityResult]:
    if not _allowed(ctx, Permission.REFUNDS_CHECK_OWN):
        return _forbidden(ctx, Permission.REFUNDS_CHECK_OWN, EligibilityResult)
    order = _owned_order(ctx, params.order_number)
    if order is None:
        return _fail(EligibilityResult, "ORDER_NOT_FOUND", "Order not found.")
    result = check_eligibility(order, params.reason, params.evidence_photo_count)
    audit.record("refund.eligibility_check", "success", principal=ctx.principal, resource_type="order",
                 resource_id=order.order_number, detail=f"{params.reason.value}:{result.rule_code}",
                 channel=ctx.channel)
    return _ok(EligibilityResult, result)


def _reject_refund(ctx: ToolContext, order_number: str, code: str):
    audit.record("refund.create", "rejected", principal=ctx.principal, resource_type="order",
                 resource_id=order_number, detail=code, channel=ctx.channel)


def _duplicate_refund(ctx: ToolContext, existing: RefundRequest) -> ToolResult[CreateRefundOutput]:
    _reject_refund(ctx, existing.order.order_number, "DUPLICATE_REQUEST")
    return _fail(
        CreateRefundOutput,
        "DUPLICATE_REQUEST",
        f"A refund request ({existing.reference}) already exists for this order.",
        CreateRefundOutput(outcome="not_created", refund_request=refund_service.to_out(existing)),
    )


def create_refund_request(
    ctx: ToolContext, params: CreateRefundRequestInput
) -> ToolResult[CreateRefundOutput]:
    """Checks, in order: permission, ownership, duplicates, eligibility (re-run now), confirmation."""
    if not _allowed(ctx, Permission.REFUNDS_CREATE_OWN):
        return _forbidden(ctx, Permission.REFUNDS_CREATE_OWN, CreateRefundOutput)
    order = _owned_order(ctx, params.order_number)
    if order is None:
        return _fail(CreateRefundOutput, "ORDER_NOT_FOUND", "Order not found.")

    existing = refund_service.find_active_request(ctx.db, order.id)
    if existing is not None:
        return _duplicate_refund(ctx, existing)

    result = check_eligibility(order, params.reason, params.evidence_photo_count)

    if result.eligible is False:
        _reject_refund(ctx, order.order_number, "NOT_ELIGIBLE")
        return _fail(
            CreateRefundOutput, "NOT_ELIGIBLE", result.reason,
            CreateRefundOutput(outcome="not_created", eligibility=result),
        )
    if result.eligible is None:
        _reject_refund(ctx, order.order_number, "MANUAL_REVIEW_REQUIRED")
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
            return _duplicate_refund(ctx, existing)
        raise

    audit.record("refund.create", "success", principal=ctx.principal, resource_type="refund_request",
                 resource_id=request.reference, detail=request.status.value, channel=ctx.channel)
    return _ok(
        CreateRefundOutput,
        CreateRefundOutput(
            outcome="created",
            eligibility=result,
            status_if_created=status,
            refund_request=refund_service.to_out(request),
        ),
    )


def _duplicate_ticket(ctx: ToolContext, existing: SupportTicket) -> ToolResult[CreateTicketOutput]:
    audit.record("ticket.create", "rejected", principal=ctx.principal, resource_type="ticket",
                 resource_id=existing.reference, detail="DUPLICATE_TICKET", channel=ctx.channel)
    return _fail(
        CreateTicketOutput,
        "DUPLICATE_TICKET",
        f"An open {existing.category.value.replace('_', ' ')} ticket ({existing.reference}) already exists for this order.",
        CreateTicketOutput(outcome="not_created", ticket=ticket_service.to_out(existing)),
    )


def create_support_ticket(
    ctx: ToolContext, params: CreateSupportTicketInput
) -> ToolResult[CreateTicketOutput]:
    """Checks, in order: permission, ownership, duplicates, confirmation. Records only; nothing is executed."""
    if not _allowed(ctx, Permission.TICKETS_CREATE_OWN):
        return _forbidden(ctx, Permission.TICKETS_CREATE_OWN, CreateTicketOutput)

    order = None
    if params.order_number is not None:
        order = _owned_order(ctx, params.order_number)
        if order is None:
            return _fail(CreateTicketOutput, "ORDER_NOT_FOUND", "Order not found.")
        existing = ticket_service.find_open_ticket(ctx.db, ctx.customer.id, order.id, params.category)
        if existing is not None:
            return _duplicate_ticket(ctx, existing)

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
                return _duplicate_ticket(ctx, existing)
        raise

    audit.record("ticket.create", "success", principal=ctx.principal, resource_type="ticket",
                 resource_id=ticket.reference, channel=ctx.channel)
    return _ok(CreateTicketOutput, CreateTicketOutput(outcome="created", ticket=ticket_service.to_out(ticket)))