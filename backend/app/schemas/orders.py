from datetime import date

from pydantic import BaseModel

from app.models import DelayReason, OrderStatus, ServiceLevel
from app.schemas.common import UtcDatetime


class MeResponse(BaseModel):
    name: str
    email: str
    identity_mode: str = "demo"
    notice: str


class OrderSummary(BaseModel):
    order_number: str
    status: OrderStatus
    status_label: str
    service_level: ServiceLevel
    description: str
    destination_city: str
    order_value_cents: int
    estimated_delivery_date: date
    created_at: UtcDatetime


class OrderDetail(OrderSummary):
    origin_city: str
    shipping_fee_cents: int
    declared_value_cents: int
    delivered_at: UtcDatetime | None
    cancelled_at: UtcDatetime | None
    last_tracking_update_at: UtcDatetime | None
    delay_reason: DelayReason | None


class TrackingEvent(BaseModel):
    at: UtcDatetime
    label: str


class TrackingOut(BaseModel):
    order_number: str
    status: OrderStatus
    status_label: str
    service_level: ServiceLevel
    estimated_delivery_date: date
    last_update_at: UtcDatetime | None
    events: list[TrackingEvent]