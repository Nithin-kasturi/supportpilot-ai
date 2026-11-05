"""SupportPilot MCP server (STDIO). Run: python run_mcp_server.py   (from the backend folder)

SECURITY MODEL
- STDIO carries no user identity, so the launching client must supply a SCOPED token in the
  SUPPORTPILOT_MCP_TOKEN environment variable (issue one with POST /api/auth/mcp-token).
- The token is validated at startup AND on every call: signature, audience (mcp only; API tokens are
  refused), expiry, revocation, active user. Role and ownership are read fresh from the database.
- The same permission checks and audit logging as the API run in the shared tool layer. Staff and
  admin tokens are refused by these customer-scoped tools. No tool accepts a customer id.
- Creation tools are PREPARE-ONLY: they return a confirmation_id and never write. Only the customer can
  confirm, through POST /api/agent/confirm.
- Limitation: the token sits in the server's environment, readable by whoever controls that process.

STDIO rule: never print to stdout (it carries the protocol). Logs go to stderr.
"""

import logging
import os
import sys
from typing import Annotated, Any, Callable

from mcp.server.fastmcp import FastMCP
from pydantic import Field, ValidationError

from app.agent.actions import prepare_refund_request, prepare_support_ticket
from app.core.config import settings
from app.database.session import SessionLocal, init_db
from app.models import Customer, OrderStatus, RefundReason, TicketCategory
from app.schemas.tools import (
    CheckRefundEligibilityInput,
    GetCustomerOrdersInput,
    GetOrderStatusInput,
)
from app.security import audit, authn, tokens
from app.security.logging_filter import install_redaction
from app.security.permissions import Permission, has_permission
from app.security.rate_limit import LIMITER
from app.tools import support_tools
from app.tools.support_tools import ToolContext

install_redaction()
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("supportpilot.mcp")

mcp = FastMCP(
    "supportpilot-tools",
    instructions=(
        "Customer-scoped SwiftParcel support tools. Every result is {ok, data, error}. Creation tools only "
        "PREPARE a request and return a confirmation_id: nothing is created until the customer confirms "
        "in the SupportPilot app. Never say something was created unless the backend confirms it."
    ),
)

OrderNumber = Annotated[str, Field(description="Order number, for example SP-1004")]


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}


def _invalid(exc: ValidationError) -> dict[str, Any]:
    detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
    return _error("INVALID_INPUT", detail)


def _run(fn: Callable[[ToolContext], dict[str, Any]]) -> dict[str, Any]:
    """Authenticate on EVERY call. Nothing in tool arguments can influence identity."""
    token = os.environ.get("SUPPORTPILOT_MCP_TOKEN", "")
    with SessionLocal() as db:
        principal, reason = authn.principal_from_token(db, token, tokens.AUDIENCE_MCP) if token else (None, "missing")
        if principal is None:
            audit.record("mcp.call", "failure", detail=f"unauthenticated:{reason}", channel="mcp")
            return _error("UNAUTHENTICATED", "A valid MCP token is required.")
        allowed, _retry = LIMITER.hit(f"mcp:user:{principal.user_id}", settings.chat_rate_limit, 60)
        if not allowed:
            audit.record("rate_limit.exceeded", "rejected", principal=principal, detail="mcp", channel="mcp")
            return _error("RATE_LIMITED", "Too many requests.")
        customer = db.get(Customer, principal.customer_id) if principal.customer_id else None
        if customer is None or not has_permission(principal.role, Permission.AGENT_USE):
            audit.record("authz.denied", "denied", principal=principal, resource_type="permission",
                         resource_id=Permission.AGENT_USE.value, channel="mcp")
            return _error("FORBIDDEN", "These tools are only available to customer accounts.")
        return fn(ToolContext(db=db, customer=customer, principal=principal, channel="mcp"))


def _prepared(prompt, result) -> dict[str, Any]:
    if prompt is None:
        return result.model_dump(mode="json")
    return {
        "ok": True,
        "data": {
            "outcome": "confirmation_required",
            "created": False,
            "confirmation_id": prompt.id,
            "title": prompt.title,
            "details": prompt.details,
            "expires_at": prompt.expires_at.isoformat(timespec="seconds") + "Z",
            "how_to_confirm": (
                "Only the customer can confirm: POST /api/agent/confirm with this confirmation_id and "
                '{"decision":"confirm"}. Nothing has been created yet.'
            ),
        },
        "error": None,
    }


@mcp.tool()
def get_order_status(order_number: OrderNumber) -> dict[str, Any]:
    """Get the status, estimated delivery and tracking timeline of one of the customer's orders."""
    try:
        params = GetOrderStatusInput(order_number=order_number)
    except ValidationError as exc:
        return _invalid(exc)
    return _run(lambda ctx: support_tools.get_order_status(ctx, params).model_dump(mode="json"))


@mcp.tool()
def get_customer_orders(
    status: Annotated[OrderStatus | None, Field(description="Optional status filter")] = None,
    limit: Annotated[int, Field(description="Maximum orders to return (1-50)")] = 25,
) -> dict[str, Any]:
    """List the customer's orders, newest first."""
    try:
        params = GetCustomerOrdersInput(status=status, limit=limit)
    except ValidationError as exc:
        return _invalid(exc)
    return _run(lambda ctx: support_tools.get_customer_orders(ctx, params).model_dump(mode="json"))


@mcp.tool()
def check_refund_eligibility(
    order_number: OrderNumber,
    reason: Annotated[RefundReason, Field(description="Why the customer wants a refund")],
    evidence_photo_count: Annotated[int, Field(description="Photos the customer can provide (damage claims)")] = 0,
) -> dict[str, Any]:
    """Evaluate refund eligibility with the backend's deterministic rules. Read-only; the decision is final."""
    try:
        params = CheckRefundEligibilityInput(
            order_number=order_number, reason=reason, evidence_photo_count=evidence_photo_count
        )
    except ValidationError as exc:
        return _invalid(exc)
    return _run(lambda ctx: support_tools.check_refund_eligibility(ctx, params).model_dump(mode="json"))


@mcp.tool()
def create_refund_request(
    order_number: OrderNumber,
    reason: Annotated[RefundReason, Field(description="Why the customer wants a refund")],
    evidence_photo_count: Annotated[int, Field(description="Photos the customer can provide")] = 0,
    customer_note: Annotated[str | None, Field(description="Optional note, max 500 characters")] = None,
) -> dict[str, Any]:
    """PREPARE a refund request. Does NOT create it: returns a confirmation_id only the customer can confirm."""
    if not 0 <= evidence_photo_count <= 20:
        return _error("INVALID_INPUT", "evidence_photo_count must be between 0 and 20.")
    return _run(
        lambda ctx: _prepared(
            *prepare_refund_request(
                ctx, order_number=order_number.strip().upper(), reason=reason,
                photos=evidence_photo_count, note=customer_note,
            )
        )
    )


@mcp.tool()
def create_support_ticket(
    category: Annotated[TicketCategory, Field(description="Ticket category")],
    description: Annotated[str, Field(description="What went wrong, 10 to 2000 characters")],
    order_number: Annotated[str | None, Field(description="Optional related order number")] = None,
) -> dict[str, Any]:
    """PREPARE a support ticket. Does NOT create it: returns a confirmation_id only the customer can confirm."""
    return _run(
        lambda ctx: _prepared(
            *prepare_support_ticket(
                ctx,
                order_number=order_number.strip().upper() if order_number else None,
                category=category,
                description=description.strip(),
            )
        )
    )


def main() -> None:
    try:
        settings.validate_for_serving()
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    init_db()
    token = os.environ.get("SUPPORTPILOT_MCP_TOKEN", "")
    with SessionLocal() as db:
        principal, reason = authn.principal_from_token(db, token, tokens.AUDIENCE_MCP) if token else (None, "missing")
    if principal is None:
        logger.error("Refusing to start: SUPPORTPILOT_MCP_TOKEN is %s. Issue one via POST /api/auth/mcp-token.", reason)
        sys.exit(1)
    logger.warning("MCP server starting for a %s account. Transport: stdio.", principal.role.value)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()