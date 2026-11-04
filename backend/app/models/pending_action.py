import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base, utcnow
from app.models.entities import _enum


class PendingActionType(enum.StrEnum):
    REFUND_REQUEST = "refund_request"
    SUPPORT_TICKET = "support_ticket"


class PendingActionStatus(enum.StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


class PendingAction(Base):
    """A sensitive operation waiting for the customer's explicit confirmation.

    The parameters are stored server-side when the action is prepared, so the confirmation can only
    ever execute exactly this operation. It is single-use and expires.
    """

    __tablename__ = "pending_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    action_type: Mapped[PendingActionType] = mapped_column(_enum(PendingActionType))
    params_json: Mapped[str] = mapped_column(Text)
    status: Mapped[PendingActionStatus] = mapped_column(
        _enum(PendingActionStatus), default=PendingActionStatus.PENDING, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)