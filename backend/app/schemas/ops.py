from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models import RefundReason, RefundStatus, TicketCategory, TicketStatus, UserRole
from app.schemas.auth import EmailStr, PersonName
from app.schemas.common import UtcDatetime


class StaffTicketOut(BaseModel):
    reference: str
    order_number: str | None
    category: TicketCategory
    status: TicketStatus
    subject: str
    description: str
    customer_name: str
    customer_email: str  # masked
    created_at: UtcDatetime
    updated_at: UtcDatetime


class StaffRefundOut(BaseModel):
    reference: str
    order_number: str
    reason: RefundReason
    status: RefundStatus
    amount_cents: int
    requires_support_approval: bool
    evidence_photo_count: int
    customer_note: str | None
    customer_name: str
    customer_email: str  # masked
    created_at: UtcDatetime


class TicketStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TicketStatus


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    customer_id: int | None
    created_at: UtcDatetime
    last_login_at: UtcDatetime | None


class CreateUserIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    full_name: PersonName
    password: Annotated[str, StringConstraints(min_length=12, max_length=128)]
    role: UserRole
    customer_email: EmailStr | None = None


class RoleChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["support_agent", "admin"]


class ActiveChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: bool


class AuditOut(BaseModel):
    id: int
    created_at: UtcDatetime
    user_id: int | None
    role: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    outcome: str
    detail: str | None
    channel: str
    ip: str | None
    email_hash: str | None