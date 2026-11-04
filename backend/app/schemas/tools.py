from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import OrderStatus, RefundReason, RefundStatus, TicketCategory
from app.schemas.orders import OrderSummary
from app.schemas.refunds import EligibilityResult, RefundRequestOut
from app.schemas.tickets import TicketOut

T = TypeVar("T")

OrderNumberStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=20, pattern=r"^[A-Za-z0-9-]+$"),
]
NoteStr = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
SubjectStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=150)]
DescriptionStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]


class ToolInput(BaseModel):
    """Tool inputs never contain a customer id, and unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class ToolError(BaseModel):
    code: str
    message: str


class ToolResult(BaseModel, Generic[T]):
    ok: bool
    data: T | None = None
    error: ToolError | None = None


class GetOrderStatusInput(ToolInput):
    order_number: OrderNumberStr


class GetCustomerOrdersInput(ToolInput):
    status: OrderStatus | None = None
    limit: int = Field(default=25, ge=1, le=50)


class CustomerOrdersOutput(BaseModel):
    count: int
    orders: list[OrderSummary]


class CheckRefundEligibilityInput(ToolInput):
    order_number: OrderNumberStr
    reason: RefundReason
    evidence_photo_count: int = Field(default=0, ge=0, le=20)


class CreateRefundRequestInput(ToolInput):
    order_number: OrderNumberStr
    reason: RefundReason
    evidence_photo_count: int = Field(default=0, ge=0, le=20)
    customer_note: NoteStr | None = None
    confirmed: bool = False


class CreateRefundOutput(BaseModel):
    outcome: Literal["confirmation_required", "created", "not_created"]
    eligibility: EligibilityResult | None = None
    status_if_created: RefundStatus | None = None
    refund_request: RefundRequestOut | None = None


class CreateSupportTicketInput(ToolInput):
    order_number: OrderNumberStr | None = None
    category: TicketCategory
    subject: SubjectStr
    description: DescriptionStr
    confirmed: bool = False


class TicketPreview(BaseModel):
    order_number: str | None
    category: TicketCategory
    subject: str
    description: str


class CreateTicketOutput(BaseModel):
    outcome: Literal["confirmation_required", "created", "not_created"]
    preview: TicketPreview | None = None
    ticket: TicketOut | None = None