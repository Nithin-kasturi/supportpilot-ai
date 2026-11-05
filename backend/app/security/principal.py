from dataclasses import dataclass

from app.models import UserRole


@dataclass(frozen=True)
class Principal:
    """The authenticated identity for one request. Built from a validated token plus a fresh database read."""

    user_id: int
    role: UserRole
    customer_id: int | None
    full_name: str
    jti: str
    audience: str