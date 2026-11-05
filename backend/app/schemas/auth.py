from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models import UserRole

EmailStr = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class ProfileOut(BaseModel):
    id: int
    email: str
    name: str
    role: UserRole


class UpdateProfileIn(BaseModel):
    """Only the display name. extra=forbid means a smuggled 'role' or 'is_active' is rejected (mass assignment)."""

    model_config = ConfigDict(extra="forbid")
    name: PersonName


class McpTokenOut(BaseModel):
    token: str
    audience: str
    expires_at: datetime