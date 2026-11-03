from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.core.demo_identity import DEMO_IDENTITY_NOTICE, get_current_customer
from app.database.session import get_db
from app.models import Customer, OrderStatus
from app.schemas.orders import MeResponse, OrderDetail, OrderSummary, TrackingOut
from app.services import order_service
from app.services.order_service import OrderNotFoundError

router = APIRouter(prefix="/api", tags=["orders"])

OrderNumber = Annotated[str, Path(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9-]+$")]
CurrentCustomer = Annotated[Customer, Depends(get_current_customer)]
DbSession = Annotated[Session, Depends(get_db)]


def _get_order_or_404(db: Session, customer: Customer, order_number: str):
    try:
        return order_service.get_order(db, customer.id, order_number)
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found.")


@router.get("/me", response_model=MeResponse)
def me(customer: CurrentCustomer) -> MeResponse:
    return MeResponse(name=customer.name, email=customer.email, notice=DEMO_IDENTITY_NOTICE)


@router.get("/orders", response_model=list[OrderSummary])
def list_my_orders(
    customer: CurrentCustomer, db: DbSession, status: OrderStatus | None = None
) -> list[OrderSummary]:
    return [order_service.to_summary(o) for o in order_service.list_orders(db, customer.id, status)]


@router.get("/orders/{order_number}", response_model=OrderDetail)
def get_my_order(order_number: OrderNumber, customer: CurrentCustomer, db: DbSession) -> OrderDetail:
    return order_service.to_detail(_get_order_or_404(db, customer, order_number))


@router.get("/orders/{order_number}/tracking", response_model=TrackingOut)
def get_my_order_tracking(
    order_number: OrderNumber, customer: CurrentCustomer, db: DbSession
) -> TrackingOut:
    return order_service.build_tracking(_get_order_or_404(db, customer, order_number))