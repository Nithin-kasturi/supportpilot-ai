"""DEVELOPMENT-ONLY demo identity.

THIS IS NOT AUTHENTICATION. The "current customer" is a fixed synthetic customer chosen by a
server-side setting (DEMO_CUSTOMER_EMAIL). Nothing in a request (headers, body, path, chat text,
LLM output) can change it. Milestone 5 replaces `get_current_customer` with real authentication;
routes depend only on this one function, so they will not change.
"""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.models import Customer

logger = logging.getLogger("uvicorn.error")

DEMO_IDENTITY_NOTICE = "Demo customer with synthetic data. This is not authentication."


def log_demo_identity_warning() -> None:
    logger.warning(
        "DEMO IDENTITY ACTIVE: acting as %s. This is NOT authentication; development only.",
        settings.demo_customer_email,
    )


def resolve_demo_customer(db: Session) -> Customer | None:
    return db.scalar(select(Customer).where(Customer.email == settings.demo_customer_email))


def get_current_customer(db: Annotated[Session, Depends(get_db)]) -> Customer:
    customer = resolve_demo_customer(db)
    if customer is None:
        raise HTTPException(
            status_code=503,
            detail="Demo customer not found. Run: python -m app.database.seed",
        )
    return customer