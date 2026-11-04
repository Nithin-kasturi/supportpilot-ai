from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Order, SupportTicket, TicketCategory, TicketStatus
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


def find_open_ticket(
    db: Session, customer_id: int, order_id: int, category: TicketCategory
) -> SupportTicket | None:
    return db.scalar(
        select(SupportTicket)
        .options(joinedload(SupportTicket.order))
        .where(
            SupportTicket.customer_id == customer_id,
            SupportTicket.order_id == order_id,
            SupportTicket.category == category,
            SupportTicket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS]),
        )
    )


def create_ticket(
    db: Session,
    *,
    customer_id: int,
    order: Order | None,
    category: TicketCategory,
    subject: str,
    description: str,
) -> SupportTicket:
    ticket = SupportTicket(
        customer_id=customer_id,
        order=order,
        category=category,
        status=TicketStatus.OPEN,
        subject=subject,
        description=description,
    )
    db.add(ticket)
    db.flush()
    return ticket