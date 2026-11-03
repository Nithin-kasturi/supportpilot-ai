from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import RefundRequest
from app.schemas.refunds import RefundRequestOut


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