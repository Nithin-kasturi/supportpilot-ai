from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.demo_identity import get_current_customer
from app.database.session import get_db
from app.models import Customer
from app.schemas.tickets import TicketOut
from app.schemas.tools import CreateSupportTicketInput, CreateTicketOutput, ToolResult
from app.services import ticket_service
from app.tools import support_tools
from app.tools.support_tools import ToolContext

router = APIRouter(prefix="/api", tags=["tickets"])

CurrentCustomer = Annotated[Customer, Depends(get_current_customer)]
DbSession = Annotated[Session, Depends(get_db)]

_ERROR_STATUS = {"ORDER_NOT_FOUND": 404, "DUPLICATE_TICKET": 409}


@router.get("/tickets", response_model=list[TicketOut])
def list_my_tickets(customer: CurrentCustomer, db: DbSession) -> list[TicketOut]:
    return ticket_service.list_tickets(db, customer.id)


@router.post("/tickets", response_model=ToolResult[CreateTicketOutput])
def create_my_ticket(
    body: CreateSupportTicketInput, response: Response, customer: CurrentCustomer, db: DbSession
) -> ToolResult[CreateTicketOutput]:
    result = support_tools.create_support_ticket(ToolContext(db=db, customer=customer), body)
    if not result.ok:
        response.status_code = _ERROR_STATUS.get(result.error.code, 400)
    else:
        response.status_code = 201 if result.data.outcome == "created" else 200
    return result