from pydantic import BaseModel

from app.models import RefundReason, RefundStatus
from app.schemas.common import UtcDatetime


class RefundRequestOut(BaseModel):
    reference: str
    order_number: str
    reason: RefundReason
    status: RefundStatus
    amount_cents: int
    requires_support_approval: bool
    evidence_photo_count: int
    rule_code: str
    customer_note: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime