from pydantic import BaseModel

from app.models import TicketCategory, TicketStatus
from app.schemas.common import UtcDatetime


class TicketOut(BaseModel):
    reference: str
    order_number: str | None
    category: TicketCategory
    status: TicketStatus
    subject: str
    description: str
    created_at: UtcDatetime
    updated_at: UtcDatetime