import json
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import utcnow
from app.models import PendingAction, PendingActionStatus, PendingActionType


def create_pending(
    db: Session, customer_id: int, action_type: PendingActionType, params: dict
) -> PendingAction:
    """Only one active confirmation per customer: a new one supersedes older ones."""
    now = utcnow()
    db.execute(
        update(PendingAction)
        .where(
            PendingAction.customer_id == customer_id,
            PendingAction.status == PendingActionStatus.PENDING,
        )
        .values(status=PendingActionStatus.CANCELLED, resolved_at=now)
    )
    action = PendingAction(
        customer_id=customer_id,
        action_type=action_type,
        params_json=json.dumps(params, sort_keys=True),
        expires_at=now + timedelta(minutes=settings.pending_action_ttl_minutes),
    )
    db.add(action)
    db.commit()
    return action


def get_owned(db: Session, customer_id: int, action_id: str) -> PendingAction | None:
    """Ownership is part of the query."""
    return db.scalar(
        select(PendingAction).where(
            PendingAction.id == action_id, PendingAction.customer_id == customer_id
        )
    )


def claim(db: Session, action_id: str, new_status: PendingActionStatus) -> bool:
    """Atomically move a PENDING action to another status. True only for the caller that wins."""
    result = db.execute(
        update(PendingAction)
        .where(PendingAction.id == action_id, PendingAction.status == PendingActionStatus.PENDING)
        .values(status=new_status, resolved_at=utcnow())
    )
    db.commit()
    return result.rowcount == 1


def set_status(db: Session, action_id: str, status: PendingActionStatus) -> None:
    db.execute(
        update(PendingAction)
        .where(PendingAction.id == action_id)
        .values(status=status, resolved_at=utcnow())
    )
    db.commit()