from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.demo_identity import get_current_customer
from app.database.session import get_db
from app.models import Customer
from app.schemas.tickets import TicketOut
from app.services import ticket_service

router = APIRouter(prefix="/api", tags=["tickets"])


@router.get("/tickets", response_model=list[TicketOut])
def list_my_tickets(
    customer: Annotated[Customer, Depends(get_current_customer)],
    db: Annotated[Session, Depends(get_db)],
) -> list[TicketOut]:
    return ticket_service.list_tickets(db, customer.id)