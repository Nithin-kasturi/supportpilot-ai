from sqlalchemy.orm import Session

from app.models import RevokedToken, User
from app.security import tokens
from app.security.principal import Principal


def principal_from_token(db: Session, token: str, audience: str) -> tuple[Principal | None, str]:
    """Validate a token and build a Principal from a FRESH database read.

    Returns (principal, "ok") or (None, reason). Role and active status always come from the database.
    """
    try:
        claims = tokens.decode_token(token, audience)
    except tokens.TokenExpired:
        return None, "expired"
    except tokens.TokenError:
        return None, "invalid"
    try:
        user_id = int(claims["sub"])
    except (TypeError, ValueError):
        return None, "invalid"
    if db.get(RevokedToken, claims["jti"]) is not None:
        return None, "revoked"
    user = db.get(User, user_id)
    if user is None:
        return None, "unknown_user"
    if not user.is_active:
        return None, "inactive"
    principal = Principal(
        user_id=user.id,
        role=user.role,
        customer_id=user.customer_id,
        full_name=user.full_name,
        jti=claims["jti"],
        audience=audience,
    )
    return principal, "ok"