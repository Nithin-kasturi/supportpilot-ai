from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, OrderStatus
from app.schemas.orders import OrderDetail, OrderSummary, TrackingEvent, TrackingOut

STATUS_LABELS: dict[OrderStatus, str] = {
    OrderStatus.PLACED: "Order placed",
    OrderStatus.PROCESSING: "Processing",
    OrderStatus.SHIPPED: "Shipped",
    OrderStatus.IN_TRANSIT: "In transit",
    OrderStatus.OUT_FOR_DELIVERY: "Out for delivery",
    OrderStatus.DELIVERED: "Delivered",
    OrderStatus.DELAYED: "Delivery delayed",
    OrderStatus.CANCELLED: "Cancelled",
    OrderStatus.LOST: "Reported lost",
}


class OrderNotFoundError(LookupError):
    """Raised when an order does not exist OR does not belong to the customer (indistinguishable)."""


def list_orders(db: Session, customer_id: int, status: OrderStatus | None = None) -> list[Order]:
    stmt = (
        select(Order)
        .where(Order.customer_id == customer_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    )
    if status is not None:
        stmt = stmt.where(Order.status == status)
    return list(db.scalars(stmt))


def get_order(db: Session, customer_id: int, order_number: str) -> Order:
    """Ownership is part of the query: another customer's order is never loaded."""
    order = db.scalar(
        select(Order).where(
            Order.customer_id == customer_id,
            Order.order_number == order_number.strip().upper(),
        )
    )
    if order is None:
        raise OrderNotFoundError(order_number)
    return order


def to_summary(order: Order) -> OrderSummary:
    return OrderSummary(
        order_number=order.order_number,
        status=order.status,
        status_label=STATUS_LABELS[order.status],
        service_level=order.service_level,
        description=order.description,
        destination_city=order.destination_city,
        order_value_cents=order.shipping_fee_cents + order.declared_value_cents,
        estimated_delivery_date=order.estimated_delivery_date,
        created_at=order.created_at,
    )


def to_detail(order: Order) -> OrderDetail:
    return OrderDetail(
        **to_summary(order).model_dump(),
        origin_city=order.origin_city,
        shipping_fee_cents=order.shipping_fee_cents,
        declared_value_cents=order.declared_value_cents,
        delivered_at=order.delivered_at,
        cancelled_at=order.cancelled_at,
        last_tracking_update_at=order.last_tracking_update_at,
        delay_reason=order.delay_reason,
    )


def build_tracking(order: Order) -> TrackingOut:
    """Derive a simple timeline from the order's timestamps."""
    events = [TrackingEvent(at=order.created_at, label="Order placed")]
    if order.first_scanned_at:
        events.append(
            TrackingEvent(at=order.first_scanned_at, label=f"Scanned at origin depot ({order.origin_city})")
        )
    if order.delivered_at:
        events.append(TrackingEvent(at=order.delivered_at, label=f"Delivered to {order.destination_city}"))
    if order.cancelled_at:
        events.append(TrackingEvent(at=order.cancelled_at, label="Order cancelled"))

    in_progress = order.status not in (OrderStatus.PLACED, OrderStatus.DELIVERED, OrderStatus.CANCELLED)
    if in_progress and order.last_tracking_update_at:
        label = "Last tracking update" if order.status == OrderStatus.LOST else STATUS_LABELS[order.status]
        events.append(TrackingEvent(at=order.last_tracking_update_at, label=label))

    events.sort(key=lambda e: e.at)
    return TrackingOut(
        order_number=order.order_number,
        status=order.status,
        status_label=STATUS_LABELS[order.status],
        service_level=order.service_level,
        estimated_delivery_date=order.estimated_delivery_date,
        last_update_at=order.last_tracking_update_at,
        events=events,
    )