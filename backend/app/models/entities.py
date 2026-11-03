import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base, utcnow


class OrderStatus(enum.StrEnum):
    PLACED = "placed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    DELAYED = "delayed"
    CANCELLED = "cancelled"
    LOST = "lost"  # confirmed lost by staff


class ServiceLevel(enum.StrEnum):
    EXPRESS = "express"
    STANDARD = "standard"
    ECONOMY = "economy"


class DelayReason(enum.StrEnum):
    WEATHER = "weather"
    OTHER = "other"


class ExceptionReason(enum.StrEnum):
    INCORRECT_ADDRESS = "incorrect_address"
    RECIPIENT_REFUSED = "recipient_refused"
    UNCLAIMED_AT_DEPOT = "unclaimed_at_depot"
    PROHIBITED_ITEM = "prohibited_item"


class RefundReason(enum.StrEnum):
    CANCELLED = "cancelled"
    LATE_EXPRESS = "late_express"
    LOST = "lost"
    DAMAGED = "damaged"
    BILLING_ERROR = "billing_error"
    OTHER = "other"


class RefundStatus(enum.StrEnum):
    APPROVED = "approved"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"


class TicketCategory(enum.StrEnum):
    DELIVERY_ISSUE = "delivery_issue"
    DAMAGED_PARCEL = "damaged_parcel"
    REFUND = "refund"
    CANCELLATION = "cancellation"
    COMPLAINT = "complaint"
    OTHER = "other"


class TicketStatus(enum.StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


def _enum(enum_cls: type[enum.Enum]) -> SAEnum:
    """Store enum values (lowercase text) in a plain VARCHAR column."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=32,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )


def _new_reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    orders: Mapped[list["Order"]] = relationship(back_populates="customer")
    refund_requests: Mapped[list["RefundRequest"]] = relationship(back_populates="customer")
    support_tickets: Mapped[list["SupportTicket"]] = relationship(back_populates="customer")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("shipping_fee_cents >= 0", name="ck_orders_shipping_fee_nonneg"),
        CheckConstraint("declared_value_cents >= 0", name="ck_orders_declared_value_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(20), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)

    status: Mapped[OrderStatus] = mapped_column(
        _enum(OrderStatus), default=OrderStatus.PLACED, index=True
    )
    service_level: Mapped[ServiceLevel] = mapped_column(_enum(ServiceLevel))
    description: Mapped[str] = mapped_column(String(200))
    origin_city: Mapped[str] = mapped_column(String(80))
    destination_city: Mapped[str] = mapped_column(String(80))

    shipping_fee_cents: Mapped[int]
    declared_value_cents: Mapped[int]

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    first_scanned_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    pickup_window_start: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    estimated_delivery_date: Mapped[date] = mapped_column(Date)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    last_tracking_update_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    delay_reason: Mapped[DelayReason | None] = mapped_column(_enum(DelayReason), default=None)
    exception_reason: Mapped[ExceptionReason | None] = mapped_column(
        _enum(ExceptionReason), default=None
    )

    customer: Mapped["Customer"] = relationship(back_populates="orders")
    refund_requests: Mapped[list["RefundRequest"]] = relationship(back_populates="order")
    support_tickets: Mapped[list["SupportTicket"]] = relationship(back_populates="order")


class RefundRequest(Base):
    __tablename__ = "refund_requests"
    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_refund_amount_nonneg"),
        CheckConstraint("evidence_photo_count >= 0", name="ck_refund_photos_nonneg"),
        # At most one non-rejected refund request per order.
        Index(
            "uq_refund_active_per_order",
            "order_id",
            unique=True,
            sqlite_where=text("status != 'rejected'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(
        String(20), unique=True, default=lambda: _new_reference("RR")
    )
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)

    reason: Mapped[RefundReason] = mapped_column(_enum(RefundReason))
    status: Mapped[RefundStatus] = mapped_column(_enum(RefundStatus), index=True)
    amount_cents: Mapped[int]
    requires_support_approval: Mapped[bool] = mapped_column(default=False)
    evidence_photo_count: Mapped[int] = mapped_column(default=0)
    rule_code: Mapped[str] = mapped_column(String(60))
    customer_note: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    order: Mapped["Order"] = relationship(back_populates="refund_requests")
    customer: Mapped["Customer"] = relationship(back_populates="refund_requests")


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        # At most one open ticket per (order, category).
        Index(
            "uq_open_ticket_per_order_category",
            "order_id",
            "category",
            unique=True,
            sqlite_where=text("order_id IS NOT NULL AND status IN ('open', 'in_progress')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(
        String(20), unique=True, default=lambda: _new_reference("TK")
    )
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True, default=None)

    category: Mapped[TicketCategory] = mapped_column(_enum(TicketCategory))
    status: Mapped[TicketStatus] = mapped_column(
        _enum(TicketStatus), default=TicketStatus.OPEN, index=True
    )
    subject: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    customer: Mapped["Customer"] = relationship(back_populates="support_tickets")
    order: Mapped["Order | None"] = relationship(back_populates="support_tickets")