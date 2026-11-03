from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.demo_identity import get_current_customer
from app.database.session import get_db
from app.models import Customer
from app.schemas.refunds import RefundRequestOut
from app.services import refund_service

router = APIRouter(prefix="/api", tags=["refunds"])


@router.get("/refund-requests", response_model=list[RefundRequestOut])
def list_my_refund_requests(
    customer: Annotated[Customer, Depends(get_current_customer)],
    db: Annotated[Session, Depends(get_db)],
) -> list[RefundRequestOut]:
    return refund_service.list_refund_requests(db, customer.id)