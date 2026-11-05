from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database.session import get_db
from app.models import Order, RefundRequest, RefundStatus, SupportTicket, TicketStatus
from app.schemas.ops import ReviewIn, StaffRefundOut, StaffTicketOut, TicketStatusIn
from app.schemas.orders import OrderDetail
from app.security import audit, pii
from app.security.deps import require_permission
from app.security.permissions import Permission
from app.security.principal import Principal
from app.services import order_service

router = APIRouter(prefix="/api/staff", tags=["staff"])

DbSession = Annotated[Session, Depends(get_db)]
Reference = Annotated[str, Path(min_length=6, max_length=20, pattern=r"^[A-Za-z]{2}-[A-Za-z0-9]{4,16}$")]
OrderNumber = Annotated[str, Path(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9-]+$")]

_TICKET_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.OPEN: {TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED},
    TicketStatus.IN_PROGRESS: {TicketStatus.OPEN, TicketStatus.RESOLVED},
    TicketStatus.RESOLVED: {TicketStatus.IN_PROGRESS, TicketStatus.CLOSED},
    TicketStatus.CLOSED: set(),
}


def _ticket_out(t: SupportTicket) -> StaffTicketOut:
    return StaffTicketOut(
        reference=t.reference,
        order_number=t.order.order_number if t.order else None,
        category=t.category,
        status=t.status,
        subject=t.subject,
        description=t.description,
        customer_name=t.customer.name,
        customer_email=pii.mask_email(t.customer.email),
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _refund_out(r: RefundRequest) -> StaffRefundOut:
    return StaffRefundOut(
        reference=r.reference,
        order_number=r.order.order_number,
        reason=r.reason,
        status=r.status,
        amount_cents=r.amount_cents,
        requires_support_approval=r.requires_support_approval,
        evidence_photo_count=r.evidence_photo_count,
        customer_note=r.customer_note,
        customer_name=r.customer.name,
        customer_email=pii.mask_email(r.customer.email),
        created_at=r.created_at,
    )


@router.get("/tickets", response_model=list[StaffTicketOut])
def list_tickets(
    principal: Annotated[Principal, Depends(require_permission(Permission.TICKETS_READ_ANY))],
    db: DbSession,
    status: TicketStatus | None = None,
) -> list[StaffTicketOut]:
    stmt = (
        select(SupportTicket)
        .options(joinedload(SupportTicket.order), joinedload(SupportTicket.customer))
        .order_by(SupportTicket.created_at.desc())
        .limit(200)
    )
    if status is not None:
        stmt = stmt.where(SupportTicket.status == status)
    rows = list(db.scalars(stmt))
    audit.record("staff.ticket.list", "success", principal=principal, resource_type="ticket",
                 detail=f"count={len(rows)}")
    return [_ticket_out(t) for t in rows]


@router.patch("/tickets/{reference}/status", response_model=StaffTicketOut)
def update_ticket_status(
    reference: Reference,
    body: TicketStatusIn,
    principal: Annotated[Principal, Depends(require_permission(Permission.TICKETS_UPDATE_STATUS))],
    db: DbSession,
) -> StaffTicketOut:
    ticket = db.scalar(
        select(SupportTicket)
        .options(joinedload(SupportTicket.order), joinedload(SupportTicket.customer))
        .where(SupportTicket.reference == reference.upper())
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    if body.status not in _TICKET_TRANSITIONS[ticket.status]:
        audit.record("ticket.status_update", "rejected", principal=principal, resource_type="ticket",
                     resource_id=ticket.reference, detail=f"{ticket.status.value}->{body.status.value}")
        raise HTTPException(status_code=409, detail="That status change is not allowed.")
    old = ticket.status
    ticket.status = body.status
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        audit.record("ticket.status_update", "rejected", principal=principal, resource_type="ticket",
                     resource_id=reference.upper(), detail="duplicate_open_ticket")
        raise HTTPException(status_code=409, detail="Another open ticket of this kind exists for the order.")
    audit.record("ticket.status_update", "success", principal=principal, resource_type="ticket",
                 resource_id=ticket.reference, detail=f"{old.value}->{body.status.value}")
    return _ticket_out(ticket)


@router.get("/refund-requests", response_model=list[StaffRefundOut])
def list_refund_requests(
    principal: Annotated[Principal, Depends(require_permission(Permission.REFUNDS_READ_ANY))],
    db: DbSession,
    status: RefundStatus | None = None,
) -> list[StaffRefundOut]:
    stmt = (
        select(RefundRequest)
        .options(joinedload(RefundRequest.order), joinedload(RefundRequest.customer))
        .order_by(RefundRequest.created_at.desc())
        .limit(200)
    )
    if status is not None:
        stmt = stmt.where(RefundRequest.status == status)
    rows = list(db.scalars(stmt))
    audit.record("staff.refund.list", "success", principal=principal, resource_type="refund_request",
                 detail=f"count={len(rows)}")
    return [_refund_out(r) for r in rows]


@router.post("/refund-requests/{reference}/review", response_model=StaffRefundOut)
def review_refund_request(
    reference: Reference,
    body: ReviewIn,
    principal: Annotated[Principal, Depends(require_permission(Permission.REFUNDS_REVIEW))],
    db: DbSession,
) -> StaffRefundOut:
    """Records a decision only. No refund is executed and no money moves."""
    request = db.scalar(
        select(RefundRequest)
        .options(joinedload(RefundRequest.order), joinedload(RefundRequest.customer))
        .where(RefundRequest.reference == reference.upper())
    )
    if request is None:
        raise HTTPException(status_code=404, detail="Refund request not found.")
    if request.status != RefundStatus.PENDING_REVIEW:
        audit.record("refund.review", "rejected", principal=principal, resource_type="refund_request",
                     resource_id=request.reference, detail=f"not_pending:{request.status.value}")
        raise HTTPException(status_code=409, detail="Only requests pending review can be reviewed.")
    request.status = RefundStatus.APPROVED if body.decision == "approve" else RefundStatus.REJECTED
    db.commit()
    audit.record("refund.review", "success", principal=principal, resource_type="refund_request",
                 resource_id=request.reference, detail=body.decision)
    return _refund_out(request)


@router.get("/orders/{order_number}", response_model=OrderDetail)
def view_order(
    order_number: OrderNumber,
    principal: Annotated[Principal, Depends(require_permission(Permission.ORDERS_READ_ANY))],
    db: DbSession,
) -> OrderDetail:
    order = db.scalar(select(Order).where(Order.order_number == order_number.strip().upper()))
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    audit.record("staff.order.view", "success", principal=principal, resource_type="order",
                 resource_id=order.order_number)
    return order_service.to_detail(order)