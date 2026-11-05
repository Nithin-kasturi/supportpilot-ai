from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from app.models import OrderStatus
from app.schemas.orders import OrderDetail, OrderSummary, TrackingOut
from app.security import audit
from app.security.deps import customer_context
from app.security.permissions import Permission
from app.services import order_service
from app.services.order_service import OrderNotFoundError
from app.tools.support_tools import ToolContext

router = APIRouter(prefix="/api", tags=["orders"])

OrderNumber = Annotated[str, Path(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9-]+$")]
OrdersCtx = Annotated[ToolContext, Depends(customer_context(Permission.ORDERS_READ_OWN))]


def _owned_order_or_404(ctx: ToolContext, order_number: str):
    try:
        order = order_service.get_order(ctx.db, ctx.customer.id, order_number)
    except OrderNotFoundError:
        audit.record_denied_lookup(ctx.principal, "order", order_number.strip().upper())
        raise HTTPException(status_code=404, detail="Order not found.")
    audit.record("order.view", "success", principal=ctx.principal, resource_type="order",
                 resource_id=order.order_number)
    return order


@router.get("/orders", response_model=list[OrderSummary])
def list_my_orders(ctx: OrdersCtx, status: OrderStatus | None = None) -> list[OrderSummary]:
    orders = order_service.list_orders(ctx.db, ctx.customer.id, status)
    audit.record("order.list", "success", principal=ctx.principal, resource_type="order",
                 detail=f"count={len(orders)}")
    return [order_service.to_summary(o) for o in orders]


@router.get("/orders/{order_number}", response_model=OrderDetail)
def get_my_order(order_number: OrderNumber, ctx: OrdersCtx) -> OrderDetail:
    return order_service.to_detail(_owned_order_or_404(ctx, order_number))


@router.get("/orders/{order_number}/tracking", response_model=TrackingOut)
def get_my_order_tracking(order_number: OrderNumber, ctx: OrdersCtx) -> TrackingOut:
    return order_service.build_tracking(_owned_order_or_404(ctx, order_number))