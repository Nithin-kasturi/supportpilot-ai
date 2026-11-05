"""User administration CLI (development and bootstrap).

  python -m app.security.manage create-user --email E --name N --role customer --customer-email CE
  python -m app.security.manage seed-dev-users     (APP_ENV=development and DEV_SEED_PASSWORD only)
  python -m app.security.manage list-users

Passwords are read with getpass or from DEV_SEED_PASSWORD, never from command-line arguments, and are
never printed. Dev users are not hardcoded: their password comes from your local .env.
"""

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import SessionLocal, init_db
from app.models import Customer, User, UserRole
from app.security import passwords

DEV_STAFF = [
    ("agent.sam@example.com", "Sam Agent", UserRole.SUPPORT_AGENT),
    ("admin.alex@example.com", "Alex Admin", UserRole.ADMIN),
]


def _create(db: Session, email: str, name: str, role: UserRole, password: str, customer_id: int | None) -> bool:
    if db.scalar(select(User).where(User.email == email.lower())) is not None:
        return False
    db.add(
        User(email=email.lower(), full_name=name, password_hash=passwords.hash_password(password),
             role=role, customer_id=customer_id)
    )
    db.commit()
    return True


def cmd_create_user(args: argparse.Namespace) -> None:
    role = UserRole(args.role)
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    problem = passwords.validate_password_strength(first)
    if problem:
        sys.exit(problem)
    with SessionLocal() as db:
        customer_id = None
        if role == UserRole.CUSTOMER:
            customer = db.scalar(select(Customer).where(Customer.email == (args.customer_email or "").lower()))
            if customer is None:
                sys.exit("Customer accounts need --customer-email of an existing customer record.")
            customer_id = customer.id
        elif args.customer_email:
            sys.exit("Staff accounts must not be linked to a customer.")
        print("created" if _create(db, args.email, args.name, role, first, customer_id) else "already exists")


def cmd_seed_dev_users(_: argparse.Namespace) -> None:
    if settings.app_env != "development":
        sys.exit("Refusing: dev users can only be seeded when APP_ENV=development.")
    if settings.dev_seed_password is None:
        sys.exit("Set DEV_SEED_PASSWORD in backend/.env (12+ characters).")
    password = settings.dev_seed_password.get_secret_value()
    problem = passwords.validate_password_strength(password)
    if problem:
        sys.exit(f"DEV_SEED_PASSWORD: {problem}")
    created = 0
    with SessionLocal() as db:
        for customer in db.scalars(select(Customer)):
            created += _create(db, customer.email, customer.name, UserRole.CUSTOMER, password, customer.id)
        for email, name, role in DEV_STAFF:
            created += _create(db, email, name, role, password, None)
    print(f"created {created} user(s); all dev users share DEV_SEED_PASSWORD from your .env")


def cmd_list_users(_: argparse.Namespace) -> None:
    with SessionLocal() as db:
        for u in db.scalars(select(User).order_by(User.id)):
            print(f"{u.id:>3}  {u.role.value:<14} active={u.is_active!s:<5} {u.email}")


def main() -> None:
    init_db()
    parser = argparse.ArgumentParser(description="SupportPilot user administration.")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", required=True, choices=[r.value for r in UserRole])
    create.add_argument("--customer-email")
    create.set_defaults(func=cmd_create_user)
    sub.add_parser("seed-dev-users").set_defaults(func=cmd_seed_dev_users)
    sub.add_parser("list-users").set_defaults(func=cmd_list_users)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()