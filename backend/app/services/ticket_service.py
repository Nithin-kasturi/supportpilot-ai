from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import SupportTicket
from app.schemas.tickets import TicketOut


def to_out(ticket: SupportTicket) -> TicketOut:
    return TicketOut(
        reference=ticket.reference,
        order_number=ticket.order.order_number if ticket.order else None,
        category=ticket.category,
        status=ticket.status,
        subject=ticket.subject,
        description=ticket.description,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def list_tickets(db: Session, customer_id: int) -> list[TicketOut]:
    rows = db.scalars(
        select(SupportTicket)
        .options(joinedload(SupportTicket.order))
        .where(SupportTicket.customer_id == customer_id)
        .order_by(SupportTicket.created_at.desc(), SupportTicket.id.desc())
    )
    return [to_out(t) for t in rows]