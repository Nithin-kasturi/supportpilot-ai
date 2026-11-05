import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import utcnow
from app.models import RevokedToken

AUDIENCE_API = "supportpilot-api"
AUDIENCE_MCP = "supportpilot-mcp"
_REQUIRED = ["exp", "iat", "sub", "jti", "aud", "iss"]


class TokenError(Exception):
    pass


class TokenExpired(TokenError):
    pass


def _secret() -> str:
    if settings.jwt_secret is None:
        raise TokenError("JWT secret is not configured.")
    return settings.jwt_secret.get_secret_value()


def _ts(moment: datetime) -> int:
    return int(moment.replace(tzinfo=timezone.utc).timestamp())


def create_token(user_id: int, audience: str, minutes: int) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at). The role is deliberately NOT in the token."""
    now = utcnow()
    expires = now + timedelta(minutes=minutes)
    jti = uuid.uuid4().hex
    payload = {
        "iss": settings.jwt_issuer,
        "aud": audience,
        "sub": str(user_id),
        "jti": jti,
        "iat": _ts(now),
        "exp": _ts(expires),
    }
    return jwt.encode(payload, _secret(), algorithm=settings.jwt_algorithm), jti, expires


def decode_token(token: str, audience: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            _secret(),
            algorithms=[settings.jwt_algorithm],  # pinned: rejects alg=none and algorithm confusion
            audience=audience,
            issuer=settings.jwt_issuer,
            options={"require": _REQUIRED},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpired("expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("invalid") from exc


def revoke_token(db: Session, claims: dict[str, Any]) -> None:
    expires = datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc).replace(tzinfo=None)
    if db.get(RevokedToken, claims["jti"]) is None:
        db.add(RevokedToken(jti=claims["jti"], user_id=int(claims["sub"]), expires_at=expires))
    db.execute(delete(RevokedToken).where(RevokedToken.expires_at < utcnow()))
    db.commit()