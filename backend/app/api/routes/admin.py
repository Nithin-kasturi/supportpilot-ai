from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import Customer, User, UserRole
from app.schemas.ops import ActiveChangeIn, AuditOut, CreateUserIn, RoleChangeIn, UserOut
from app.security import audit, passwords
from app.security.deps import require_permission
from app.security.permissions import Permission
from app.security.principal import Principal

router = APIRouter(prefix="/api/admin", tags=["admin"])

DbSession = Annotated[Session, Depends(get_db)]
UsersAdmin = Annotated[Principal, Depends(require_permission(Permission.USERS_MANAGE))]
AuditReader = Annotated[Principal, Depends(require_permission(Permission.AUDIT_READ))]


def _user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id, email=u.email, full_name=u.full_name, role=u.role, is_active=u.is_active,
        customer_id=u.customer_id, created_at=u.created_at, last_login_at=u.last_login_at,
    )


def _other_active_admins(db: Session, exclude_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(User).where(
            User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != exclude_id
        )
    ) or 0


@router.get("/users", response_model=list[UserOut])
def list_users(principal: UsersAdmin, db: DbSession) -> list[UserOut]:
    rows = list(db.scalars(select(User).order_by(User.id)))
    audit.record("admin.user.list", "success", principal=principal, resource_type="user",
                 detail=f"count={len(rows)}")
    return [_user_out(u) for u in rows]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: CreateUserIn, principal: UsersAdmin, db: DbSession) -> UserOut:
    problem = passwords.validate_password_strength(body.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)

    customer_id = None
    if body.role == UserRole.CUSTOMER:
        if not body.customer_email:
            raise HTTPException(status_code=422, detail="Customer accounts need customer_email.")
        customer = db.scalar(select(Customer).where(Customer.email == body.customer_email))
        if customer is None:
            raise HTTPException(status_code=422, detail="No customer record with that email.")
        customer_id = customer.id
    elif body.customer_email:
        raise HTTPException(status_code=422, detail="Staff accounts must not be linked to a customer.")

    user = User(
        email=body.email, full_name=body.full_name, password_hash=passwords.hash_password(body.password),
        role=body.role, customer_id=customer_id,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        audit.record("admin.user.create", "rejected", principal=principal, resource_type="user",
                     detail="duplicate_email_or_customer")
        raise HTTPException(status_code=409, detail="That email or customer is already linked to an account.")
    audit.record("admin.user.create", "success", principal=principal, resource_type="user",
                 resource_id=str(user.id), detail=user.role.value)
    return _user_out(user)


@router.patch("/users/{user_id}/role", response_model=UserOut)
def change_role(user_id: int, body: RoleChangeIn, principal: UsersAdmin, db: DbSession) -> UserOut:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")

    def reject(code: str, message: str):
        audit.record("admin.role_change", "rejected", principal=principal, resource_type="user",
                     resource_id=str(user_id), detail=code)
        raise HTTPException(status_code=409, detail=message)

    if target.id == principal.user_id:
        reject("self_change", "You cannot change your own role.")
    if target.role == UserRole.CUSTOMER:
        reject("customer_locked", "Customer accounts cannot be promoted. Create a separate staff account.")
    new_role = UserRole(body.role)
    if target.role == UserRole.ADMIN and new_role != UserRole.ADMIN and _other_active_admins(db, target.id) == 0:
        reject("last_admin", "At least one active administrator must remain.")

    old = target.role
    target.role = new_role
    db.commit()
    audit.record("admin.role_change", "success", principal=principal, resource_type="user",
                 resource_id=str(user_id), detail=f"{old.value}->{new_role.value}")
    return _user_out(target)


@router.patch("/users/{user_id}/active", response_model=UserOut)
def set_active(user_id: int, body: ActiveChangeIn, principal: UsersAdmin, db: DbSession) -> UserOut:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if not body.is_active:
        problem = None
        if target.id == principal.user_id:
            problem = ("self_deactivate", "You cannot deactivate your own account.")
        elif target.role == UserRole.ADMIN and _other_active_admins(db, target.id) == 0:
            problem = ("last_admin", "At least one active administrator must remain.")
        if problem:
            audit.record("admin.user.active", "rejected", principal=principal, resource_type="user",
                         resource_id=str(user_id), detail=problem[0])
            raise HTTPException(status_code=409, detail=problem[1])
    target.is_active = body.is_active
    db.commit()
    audit.record("admin.user.active", "success", principal=principal, resource_type="user",
                 resource_id=str(user_id), detail=f"is_active={body.is_active}")
    return _user_out(target)


@router.get("/audit", response_model=list[AuditOut])
def read_audit(
    principal: AuditReader,
    db: DbSession,
    limit: int = 50,
    action: str | None = None,
    outcome: str | None = None,
    user_id: int | None = None,
) -> list[AuditOut]:
    rows = audit.list_events(db, limit=max(1, min(limit, 200)), action=action, outcome=outcome, user_id=user_id)
    audit.record("admin.audit.view", "success", principal=principal, resource_type="audit_log",
                 detail=f"count={len(rows)}")
    return [AuditOut.model_validate(r, from_attributes=True) for r in rows]