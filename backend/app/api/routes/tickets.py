from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from app.schemas.tickets import TicketOut
from app.schemas.tools import CreateSupportTicketInput, CreateTicketOutput, ToolResult
from app.security import audit
from app.security.deps import customer_context, rate_limit_user
from app.security.permissions import Permission
from app.services import ticket_service
from app.tools import support_tools
from app.tools.support_tools import ToolContext

router = APIRouter(prefix="/api", tags=["tickets"])

Reference = Annotated[str, Path(min_length=6, max_length=20, pattern=r"^[A-Za-z]{2}-[A-Za-z0-9]{4,16}$")]
ReadCtx = Annotated[ToolContext, Depends(customer_context(Permission.TICKETS_READ_OWN))]
CreateCtx = Annotated[ToolContext, Depends(customer_context(Permission.TICKETS_CREATE_OWN))]

_ERROR_STATUS = {"ORDER_NOT_FOUND": 404, "FORBIDDEN": 403, "DUPLICATE_TICKET": 409}


@router.get("/tickets", response_model=list[TicketOut])
def list_my_tickets(ctx: ReadCtx) -> list[TicketOut]:
    rows = ticket_service.list_tickets(ctx.db, ctx.customer.id)
    audit.record("ticket.list", "success", principal=ctx.principal, resource_type="ticket",
                 detail=f"count={len(rows)}")
    return rows


@router.get("/tickets/{reference}", response_model=TicketOut)
def get_my_ticket(reference: Reference, ctx: ReadCtx) -> TicketOut:
    row = ticket_service.get_ticket(ctx.db, ctx.customer.id, reference)
    if row is None:
        audit.record_denied_lookup(ctx.principal, "ticket", reference.upper())
        raise HTTPException(status_code=404, detail="Ticket not found.")
    audit.record("ticket.view", "success", principal=ctx.principal, resource_type="ticket",
                 resource_id=row.reference)
    return row


@router.post(
    "/tickets",
    response_model=ToolResult[CreateTicketOutput],
    dependencies=[Depends(rate_limit_user("ticket_create", "sensitive_rate_limit"))],
)
def create_my_ticket(
    body: CreateSupportTicketInput, response: Response, ctx: CreateCtx
) -> ToolResult[CreateTicketOutput]:
    result = support_tools.create_support_ticket(ctx, body)
    if not result.ok:
        response.status_code = _ERROR_STATUS.get(result.error.code, 400)
    else:
        response.status_code = 201 if result.data.outcome == "created" else 200
    return result