from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db, utcnow
from app.models import Customer, User
from app.schemas.auth import LoginRequest, McpTokenOut, ProfileOut, UpdateProfileIn
from app.security import audit, passwords, tokens
from app.security.deps import enforce_csrf, extract_token, get_principal, rate_limit_user, require_permission
from app.security.permissions import Permission
from app.security.principal import Principal
from app.security.rate_limit import LIMITER, client_ip

router = APIRouter(prefix="/api", tags=["auth"])

DbSession = Annotated[Session, Depends(get_db)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def _profile(user: User) -> ProfileOut:
    return ProfileOut(id=user.id, email=user.email, name=user.full_name, role=user.role)


def _cookie_args() -> dict:
    return {
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "path": "/",
    }


@router.post("/auth/login", response_model=ProfileOut)
def login(body: LoginRequest, request: Request, response: Response, db: DbSession) -> ProfileOut:
    enforce_csrf(request)
    ip = client_ip(request)
    digest = audit.email_digest(body.email)

    for key, limit in (
        (f"login:ip:{ip}", settings.login_rate_limit_per_ip),
        (f"login:acct:{digest}", settings.login_rate_limit_per_account),
    ):
        allowed, retry = LIMITER.hit(key, limit, 60)
        if not allowed:
            audit.record("auth.login", "rejected", ip=ip, email_hash=digest, detail="rate_limited")
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please wait and try again.",
                headers={"Retry-After": str(retry)},
            )

    user = db.scalar(select(User).where(User.email == body.email))
    reason = "bad_credentials"
    ok = False
    if user is None:
        passwords.verify_dummy(body.password)  # same cost as a real check
    elif passwords.verify_password(user.password_hash, body.password):
        if user.is_active:
            ok = True
        else:
            reason = "inactive"

    if not ok:
        audit.record("auth.login", "failure", user_id=user.id if user else None, ip=ip,
                     email_hash=digest, detail=reason)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(body.password)
    user.last_login_at = utcnow()
    db.commit()

    token, _, _ = tokens.create_token(user.id, tokens.AUDIENCE_API, settings.access_token_minutes)
    response.set_cookie(
        key=settings.cookie_name, value=token, max_age=settings.access_token_minutes * 60, **_cookie_args()
    )
    audit.record("auth.login", "success", user_id=user.id, role=user.role.value, ip=ip)
    return _profile(user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: DbSession) -> Response:
    enforce_csrf(request)
    token, _ = extract_token(request)
    if token:
        try:
            claims = tokens.decode_token(token, tokens.AUDIENCE_API)
            tokens.revoke_token(db, claims)
            audit.record("auth.logout", "success", user_id=int(claims["sub"]), ip=client_ip(request))
        except tokens.TokenError:
            pass
    reply = Response(status_code=204)
    reply.delete_cookie(key=settings.cookie_name, **_cookie_args())
    return reply


@router.post(
    "/auth/mcp-token",
    response_model=McpTokenOut,
    dependencies=[Depends(rate_limit_user("mcp_token", "sensitive_rate_limit"))],
)
def issue_mcp_token(
    principal: Annotated[Principal, Depends(require_permission(Permission.AGENT_USE))],
) -> McpTokenOut:
    """A separate, audience-scoped token for the MCP server. The API rejects it, and MCP rejects API tokens."""
    token, _, expires = tokens.create_token(principal.user_id, tokens.AUDIENCE_MCP, settings.mcp_token_minutes)
    audit.record("auth.mcp_token_issued", "success", principal=principal)
    return McpTokenOut(token=token, audience=tokens.AUDIENCE_MCP, expires_at=expires)


@router.get("/me", response_model=ProfileOut)
def me(principal: CurrentPrincipal, db: DbSession) -> ProfileOut:
    user = db.get(User, principal.user_id)
    return _profile(user)


@router.patch("/me", response_model=ProfileOut)
def update_me(
    body: UpdateProfileIn,
    principal: Annotated[Principal, Depends(require_permission(Permission.PROFILE_UPDATE_OWN))],
    db: DbSession,
) -> ProfileOut:
    user = db.get(User, principal.user_id)
    user.full_name = body.name
    if user.customer_id is not None:
        customer = db.get(Customer, user.customer_id)
        if customer is not None:
            customer.name = body.name
    db.commit()
    audit.record("profile.update", "success", principal=principal, resource_type="user",
                 resource_id=str(user.id), detail="name")
    return _profile(user)