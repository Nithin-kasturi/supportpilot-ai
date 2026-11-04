from pydantic import BaseModel, Field

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


class EligibilityRequest(BaseModel):
    reason: RefundReason
    evidence_photo_count: int = Field(default=0, ge=0, le=20)


class EligibilityResult(BaseModel):
    order_number: str
    refund_reason: RefundReason
    eligible: bool | None  # None = cannot be decided automatically (manual review)
    reason: str
    applicable_policy: str
    requires_support_approval: bool
    next_action: str
    refundable_amount_cents: int | None
    rule_code: str