import enum
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base, utcnow
from app.models.entities import _enum


class UserRole(enum.StrEnum):
    CUSTOMER = "customer"
    SUPPORT_AGENT = "support_agent"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Customers are linked to exactly one customer record; staff never are.
        CheckConstraint(
            "(role = 'customer' AND customer_id IS NOT NULL) OR (role != 'customer' AND customer_id IS NULL)",
            name="ck_users_customer_link",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole))
    is_active: Mapped[bool] = mapped_column(default=True)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), unique=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class RevokedToken(Base):
    """Logged-out tokens, kept until they would have expired anyway."""

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    """Security audit trail. Never stores passwords, tokens, raw emails or message text."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(default=None, index=True)
    role: Mapped[str | None] = mapped_column(String(20), default=None)
    action: Mapped[str] = mapped_column(String(60), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(40), default=None)
    resource_id: Mapped[str | None] = mapped_column(String(64), default=None)
    outcome: Mapped[str] = mapped_column(String(16), index=True)
    detail: Mapped[str | None] = mapped_column(String(200), default=None)
    channel: Mapped[str] = mapped_column(String(10), default="api")
    ip: Mapped[str | None] = mapped_column(String(45), default=None)
    email_hash: Mapped[str | None] = mapped_column(String(16), default=None)