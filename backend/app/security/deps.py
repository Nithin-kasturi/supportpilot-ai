from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.models import Customer
from app.security import audit, authn, tokens
from app.security.permissions import Permission, has_permission
from app.security.principal import Principal
from app.security.rate_limit import LIMITER, client_ip
from app.tools.support_tools import ToolContext

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER_VALUE = "SupportPilot"
DbSession = Annotated[Session, Depends(get_db)]


def extract_token(request: Request) -> tuple[str | None, bool]:
    """Returns (token, came_from_cookie). Cookie first, then Authorization: Bearer."""
    cookie = request.cookies.get(settings.cookie_name)
    if cookie:
        return cookie, True
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip(), False
    return None, False


def enforce_csrf(request: Request) -> None:
    """For unsafe methods: a present Origin must be allow-listed, and the custom header is required.

    A cross-site form or simple request cannot set the custom header, and a cross-origin fetch with it
    needs a CORS preflight that only allow-listed origins pass. SameSite cookies are the first layer."""
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.cors_origin_list:
        raise HTTPException(status_code=403, detail="Cross-site request blocked.")
    if request.headers.get("x-requested-with") != CSRF_HEADER_VALUE:
        raise HTTPException(status_code=403, detail="Cross-site request blocked.")


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401, detail="Not authenticated.", headers={"WWW-Authenticate": "Bearer"}
    )


def get_principal(request: Request, db: DbSession) -> Principal:
    token, from_cookie = extract_token(request)
    if token is None:
        raise _unauthorized()
    if from_cookie:
        enforce_csrf(request)
    principal, reason = authn.principal_from_token(db, token, tokens.AUDIENCE_API)
    if principal is None:
        audit.record("auth.token_rejected", "failure", detail=reason, ip=client_ip(request))
        raise _unauthorized()
    return principal


def require_permission(permission: Permission) -> Callable[..., Principal]:
    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if not has_permission(principal.role, permission):
            audit.record(
                "authz.denied",
                "denied",
                principal=principal,
                resource_type="permission",
                resource_id=permission.value,
            )
            raise HTTPException(
                status_code=403, detail="You do not have permission to perform this action."
            )
        return principal

    return dependency


def customer_context(permission: Permission) -> Callable[..., ToolContext]:
    """Permission check plus the customer scope. Customer identity comes ONLY from the principal."""

    def dependency(
        principal: Annotated[Principal, Depends(require_permission(permission))], db: DbSession
    ) -> ToolContext:
        customer = db.get(Customer, principal.customer_id) if principal.customer_id else None
        if customer is None:
            raise HTTPException(status_code=403, detail="This account has no customer profile.")
        return ToolContext(db=db, customer=customer, principal=principal, channel="api")

    return dependency


def rate_limit_user(scope: str, limit_attr: str, window: int = 60) -> Callable[..., None]:
    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> None:
        allowed, retry = LIMITER.hit(f"{scope}:user:{principal.user_id}", getattr(settings, limit_attr), window)
        if not allowed:
            audit.record("rate_limit.exceeded", "rejected", principal=principal, detail=scope)
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please slow down.",
                headers={"Retry-After": str(retry)},
            )

    return dependency