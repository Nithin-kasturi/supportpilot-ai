"""Structured security audit trail, written in its OWN transaction so it survives a failed operation.

Never pass passwords, tokens, raw emails or message text. Callers pass short codes in `detail`.
"""

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models import AuditLog
from app.security.principal import Principal

logger = logging.getLogger("supportpilot.audit")


def email_digest(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:12]


def record(
    action: str,
    outcome: str,
    *,
    principal: Principal | None = None,
    user_id: int | None = None,
    role: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: str | None = None,
    channel: str = "api",
    ip: str | None = None,
    email_hash: str | None = None,
) -> None:
    try:
        with SessionLocal() as db:
            db.add(
                AuditLog(
                    user_id=principal.user_id if principal else user_id,
                    role=principal.role.value if principal else role,
                    action=action[:60],
                    resource_type=resource_type,
                    resource_id=str(resource_id)[:64] if resource_id else None,
                    outcome=outcome,
                    detail=detail[:200] if detail else None,
                    channel=channel,
                    ip=ip,
                    email_hash=email_hash,
                )
            )
            db.commit()
    except Exception:
        # Audit failures are logged but do not break the request. See docs/security.md (limitations).
        logger.exception("Failed to write audit record for action %s", action)


def record_denied_lookup(
    principal: Principal, resource_type: str, resource_id: str, channel: str = "api"
) -> None:
    """A record was not found OR not owned. The caller sees the same generic 404 in both cases."""
    record(
        "record.access",
        "denied",
        principal=principal,
        resource_type=resource_type,
        resource_id=resource_id,
        detail="not_found_or_not_owner",
        channel=channel,
    )


def list_events(
    db: Session,
    *,
    limit: int = 50,
    action: str | None = None,
    outcome: str | None = None,
    user_id: int | None = None,
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 200))
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if outcome:
        stmt = stmt.where(AuditLog.outcome == outcome)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    return list(db.scalars(stmt))