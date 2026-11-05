from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Order, RefundRequest, RefundStatus
from app.schemas.refunds import EligibilityResult, RefundRequestOut


def to_out(request: RefundRequest) -> RefundRequestOut:
    return RefundRequestOut(
        reference=request.reference,
        order_number=request.order.order_number,
        reason=request.reason,
        status=request.status,
        amount_cents=request.amount_cents,
        requires_support_approval=request.requires_support_approval,
        evidence_photo_count=request.evidence_photo_count,
        rule_code=request.rule_code,
        customer_note=request.customer_note,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


def list_refund_requests(db: Session, customer_id: int) -> list[RefundRequestOut]:
    rows = db.scalars(
        select(RefundRequest)
        .options(joinedload(RefundRequest.order))
        .where(RefundRequest.customer_id == customer_id)
        .order_by(RefundRequest.created_at.desc(), RefundRequest.id.desc())
    )
    return [to_out(r) for r in rows]


def find_active_request(db: Session, order_id: int) -> RefundRequest | None:
    """A rejected request does not block a new one."""
    return db.scalar(
        select(RefundRequest)
        .options(joinedload(RefundRequest.order))
        .where(RefundRequest.order_id == order_id, RefundRequest.status != RefundStatus.REJECTED)
    )


def status_for(result: EligibilityResult) -> RefundStatus:
    """Records only. No refund is executed and no money moves."""
    return RefundStatus.PENDING_REVIEW if result.requires_support_approval else RefundStatus.APPROVED


def create_refund_request(
    db: Session,
    *,
    order: Order,
    customer_id: int,
    result: EligibilityResult,
    evidence_photo_count: int,
    note: str | None,
) -> RefundRequest:
    assert result.eligible is True and result.refundable_amount_cents is not None
    request = RefundRequest(
        order=order,
        customer_id=customer_id,
        reason=result.refund_reason,
        status=status_for(result),
        amount_cents=result.refundable_amount_cents,
        requires_support_approval=result.requires_support_approval,
        evidence_photo_count=evidence_photo_count,
        rule_code=result.rule_code,
        customer_note=note or None,
    )
    db.add(request)
    db.flush()
    return request

def get_request(db: Session, customer_id: int, reference: str) -> RefundRequestOut | None:
    """Ownership is part of the query."""
    request = db.scalar(
        select(RefundRequest)
        .options(joinedload(RefundRequest.order))
        .where(RefundRequest.customer_id == customer_id, RefundRequest.reference == reference.strip().upper())
    )
    return to_out(request) if request else None