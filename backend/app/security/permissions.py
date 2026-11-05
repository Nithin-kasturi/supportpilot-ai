import enum

from app.models import UserRole


class Permission(enum.StrEnum):
    PROFILE_READ_OWN = "profile:read_own"
    PROFILE_UPDATE_OWN = "profile:update_own"
    ORDERS_READ_OWN = "orders:read_own"
    ORDERS_READ_ANY = "orders:read_any"
    REFUNDS_CHECK_OWN = "refunds:check_own"
    REFUNDS_CREATE_OWN = "refunds:create_own"
    REFUNDS_READ_OWN = "refunds:read_own"
    REFUNDS_READ_ANY = "refunds:read_any"
    REFUNDS_REVIEW = "refunds:review"
    TICKETS_CREATE_OWN = "tickets:create_own"
    TICKETS_READ_OWN = "tickets:read_own"
    TICKETS_READ_ANY = "tickets:read_any"
    TICKETS_UPDATE_STATUS = "tickets:update_status"
    AGENT_USE = "agent:use"
    USERS_MANAGE = "users:manage"
    AUDIT_READ = "audit:read"


_PROFILE = {Permission.PROFILE_READ_OWN, Permission.PROFILE_UPDATE_OWN}

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.CUSTOMER: frozenset(
        _PROFILE
        | {
            Permission.ORDERS_READ_OWN,
            Permission.REFUNDS_CHECK_OWN,
            Permission.REFUNDS_CREATE_OWN,
            Permission.REFUNDS_READ_OWN,
            Permission.TICKETS_CREATE_OWN,
            Permission.TICKETS_READ_OWN,
            Permission.AGENT_USE,
        }
    ),
    UserRole.SUPPORT_AGENT: frozenset(
        _PROFILE
        | {
            Permission.ORDERS_READ_ANY,
            Permission.REFUNDS_READ_ANY,
            Permission.REFUNDS_REVIEW,
            Permission.TICKETS_READ_ANY,
            Permission.TICKETS_UPDATE_STATUS,
        }
    ),
    # Least privilege: administrators manage users and read audit records, not customer cases.
    UserRole.ADMIN: frozenset(_PROFILE | {Permission.USERS_MANAGE, Permission.AUDIT_READ}),
}


def has_permission(role: UserRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())