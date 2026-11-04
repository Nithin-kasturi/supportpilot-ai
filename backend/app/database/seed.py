"""Synthetic demo data. Run: python -m app.database.seed [--reset]

Everything here is fictional. Scenario orders (SP-1xxx, SP-3xxx) are dated relative to the
moment of seeding, so run with --reset to refresh them if time has passed.
"""

import argparse
import random
from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.session import Base, SessionLocal, engine, init_db, utcnow
from app.models import (
    Customer,
    DelayReason,
    ExceptionReason,
    Order,
    OrderStatus,
    RefundReason,
    RefundRequest,
    RefundStatus,
    ServiceLevel,
    SupportTicket,
    TicketCategory,
    TicketStatus,
)

DEMO_CUSTOMER_EMAIL = "maya.patel@example.com"
OTHER_CUSTOMER_EMAIL = "daniel.okafor@example.com"
RNG_SEED = 42
FILLER_COUNT = 40

CUSTOMERS = [
    ("Maya Patel", DEMO_CUSTOMER_EMAIL),
    ("Daniel Okafor", OTHER_CUSTOMER_EMAIL),
    ("Sofia Lindqvist", "sofia.lindqvist@example.com"),
    ("Arjun Mehta", "arjun.mehta@example.com"),
    ("Chloe Dubois", "chloe.dubois@example.com"),
    ("Marcus Reyes", "marcus.reyes@example.com"),
    ("Hannah Weiss", "hannah.weiss@example.com"),
    ("Kenji Tanaka", "kenji.tanaka@example.com"),
    ("Amara Nwosu", "amara.nwosu@example.com"),
    ("Lucas Ferreira", "lucas.ferreira@example.com"),
]

CITIES = [
    "Chicago", "Denver", "Austin", "Seattle", "Boston",
    "Miami", "Phoenix", "Atlanta", "Portland", "Dallas",
]
ITEMS = [
    "Laptop sleeve", "Ceramic mug set", "Running shoes", "Books (3)", "Phone case",
    "Desk lamp", "Camera lens", "Board game", "Kitchen scale", "Headphones",
    "Yoga mat", "Gift box",
]
FEES = [699, 799, 899, 1099, 1299, 1599, 1999, 2499]
DECLARED_VALUES = [1500, 2500, 3500, 5000, 8000, 12000, 20000]
SERVICE_DAYS = {ServiceLevel.EXPRESS: 2, ServiceLevel.STANDARD: 5, ServiceLevel.ECONOMY: 10}

FILLER_STATUSES = [
    OrderStatus.PLACED, OrderStatus.PROCESSING, OrderStatus.SHIPPED, OrderStatus.IN_TRANSIT,
    OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED, OrderStatus.DELAYED, OrderStatus.CANCELLED,
]
FILLER_WEIGHTS = [4, 4, 4, 6, 3, 14, 3, 2]
FILLER_LEVELS = [ServiceLevel.EXPRESS, ServiceLevel.STANDARD, ServiceLevel.STANDARD, ServiceLevel.ECONOMY]


def _days(n: int) -> timedelta:
    return timedelta(days=n)


def _hours(n: int) -> timedelta:
    return timedelta(hours=n)


def _order_kwargs(
    now: datetime,
    *,
    number: str,
    status: OrderStatus,
    level: ServiceLevel,
    description: str,
    fee: int,
    declared: int,
    created: datetime,
    est_days_ago: int,
    **extra,
) -> dict:
    n = int(number.split("-")[1])
    return {
        "order_number": number,
        "status": status,
        "service_level": level,
        "description": description,
        "origin_city": CITIES[n % len(CITIES)],
        "destination_city": CITIES[(3 * n + 1) % len(CITIES)],
        "shipping_fee_cents": fee,
        "declared_value_cents": declared,
        "created_at": created,
        "estimated_delivery_date": (now - _days(est_days_ago)).date(),
        **extra,
    }


def scenario_specs(now: datetime) -> list[tuple[str, dict]]:
    """Hand-built orders, one per refund-rule branch. Returns (customer email, order kwargs)."""
    S, X, E = ServiceLevel.STANDARD, ServiceLevel.EXPRESS, ServiceLevel.ECONOMY
    me = DEMO_CUSTOMER_EMAIL

    def o(email, number, status, level, description, fee, declared, created, est_days_ago, **extra):
        return email, _order_kwargs(
            now, number=number, status=status, level=level, description=description,
            fee=fee, declared=declared, created=created, est_days_ago=est_days_ago, **extra,
        )

    pickup_window = (now - _days(3)).replace(minute=0, second=0, microsecond=0)

    return [
        # Damaged, delivered recently, under $50 total
        o(me, "SP-1001", OrderStatus.DELIVERED, S, "Ceramic mug set", 899, 3000, now - _days(5), 0,
          first_scanned_at=now - _days(4), delivered_at=now - _hours(6),
          last_tracking_update_at=now - _hours(6)),
        # Damaged, delivered recently, $135 total (needs support approval)
        o(me, "SP-1002", OrderStatus.DELIVERED, S, "Camera lens", 1500, 12000, now - _days(6), 1,
          first_scanned_at=now - _days(5), delivered_at=now - _hours(20),
          last_tracking_update_at=now - _hours(20)),
        # Delivered 5 days ago: 48-hour damage window expired
        o(me, "SP-1003", OrderStatus.DELIVERED, S, "Desk lamp", 799, 2500, now - _days(11), 5,
          first_scanned_at=now - _days(10), delivered_at=now - _days(5),
          last_tracking_update_at=now - _days(5)),
        # Express delivered 5 days after the estimate, cause not weather
        o(me, "SP-1004", OrderStatus.DELIVERED, X, "Gift box", 2500, 4000, now - _days(13), 10,
          first_scanned_at=now - _days(12), delivered_at=now - _days(5),
          last_tracking_update_at=now - _days(5), delay_reason=DelayReason.OTHER),
        # Express late because of weather: excluded
        o(me, "SP-1005", OrderStatus.DELIVERED, X, "Winter jacket", 2800, 9000, now - _days(13), 10,
          first_scanned_at=now - _days(12), delivered_at=now - _days(5),
          last_tracking_update_at=now - _days(5), delay_reason=DelayReason.WEATHER),
        # Standard late: no automatic compensation
        o(me, "SP-1006", OrderStatus.DELIVERED, S, "Board game", 1100, 3500, now - _days(17), 12,
          first_scanned_at=now - _days(16), delivered_at=now - _days(6),
          last_tracking_update_at=now - _days(6), delay_reason=DelayReason.OTHER),
        # Express still undelivered, 5 days past the estimate
        o(me, "SP-1007", OrderStatus.DELAYED, X, "Headphones", 2200, 15000, now - _days(8), 5,
          first_scanned_at=now - _days(7), last_tracking_update_at=now - _days(2),
          delay_reason=DelayReason.OTHER),
        # Confirmed lost by staff, $98 total
        o(me, "SP-1008", OrderStatus.LOST, S, "Laptop sleeve", 1800, 8000, now - _days(20), 14,
          first_scanned_at=now - _days(19), last_tracking_update_at=now - _days(12)),
        # No tracking update for 9 days, not confirmed lost: manual review
        o(me, "SP-1009", OrderStatus.IN_TRANSIT, S, "Books (3)", 1000, 4000, now - _days(16), 9,
          first_scanned_at=now - _days(15), last_tracking_update_at=now - _days(9)),
        # Cancelled before the first scan
        o(me, "SP-1010", OrderStatus.CANCELLED, S, "Yoga mat", 1200, 3000, now - _days(4), -2,
          cancelled_at=now - _days(2), last_tracking_update_at=now - _days(2)),
        # Cancelled after the first scan
        o(me, "SP-1011", OrderStatus.CANCELLED, S, "Phone case", 1800, 2000, now - _days(5), -1,
          first_scanned_at=now - _days(4), cancelled_at=now - _days(2),
          last_tracking_update_at=now - _days(2)),
        # Active orders for tracking and status variety
        o(me, "SP-1012", OrderStatus.IN_TRANSIT, S, "Kitchen scale", 950, 2500, now - _days(2), -3,
          first_scanned_at=now - _days(1), last_tracking_update_at=now - _hours(5)),
        o(me, "SP-1013", OrderStatus.OUT_FOR_DELIVERY, X, "Running shoes", 2000, 11000, now - _days(2), 0,
          first_scanned_at=now - _days(1), last_tracking_update_at=now - _hours(1)),
        o(me, "SP-1014", OrderStatus.PLACED, E, "Gift box", 700, 1500, now - _hours(3), -9),
        o(me, "SP-1015", OrderStatus.PROCESSING, S, "Books (3)", 1000, 2800, now - _hours(20), -4,
          last_tracking_update_at=now - _hours(10)),
        # Express, failed delivery because of an incorrect address: excluded
        o(me, "SP-1016", OrderStatus.DELAYED, X, "Camera lens", 3000, 18000, now - _days(9), 6,
          first_scanned_at=now - _days(8), last_tracking_update_at=now - _days(1),
          exception_reason=ExceptionReason.INCORRECT_ADDRESS),
        # Delivered 3 hours ago, flagged prohibited item: excluded
        o(me, "SP-1017", OrderStatus.DELIVERED, S, "Mixed contents (flagged on inspection)", 1200, 2000,
          now - _days(6), 1, first_scanned_at=now - _days(5), delivered_at=now - _hours(3),
          last_tracking_update_at=now - _hours(3), exception_reason=ExceptionReason.PROHIBITED_ITEM),
        # Delivered on time 10 days ago (change of mind, billing error)
        o(me, "SP-1018", OrderStatus.DELIVERED, S, "Headphones", 899, 6000, now - _days(15), 10,
          first_scanned_at=now - _days(14), delivered_at=now - _days(10),
          last_tracking_update_at=now - _days(10)),
        # Express delivered late 38 days ago: 30-day request limit expired
        o(me, "SP-1019", OrderStatus.DELIVERED, X, "Ceramic mug set", 2100, 3000, now - _days(47), 43,
          first_scanned_at=now - _days(46), delivered_at=now - _days(38),
          last_tracking_update_at=now - _days(38), delay_reason=DelayReason.OTHER),
        # Scheduled pickup cancelled 1 hour before the window (late-cancellation fee)
        o(me, "SP-1020", OrderStatus.CANCELLED, S, "Desk lamp", 1500, 2200, now - _days(5), -1,
          pickup_window_start=pickup_window, cancelled_at=pickup_window - _hours(1),
          last_tracking_update_at=pickup_window - _hours(1)),
        o(me, "SP-1021", OrderStatus.SHIPPED, S, "Board game", 850, 3000, now - _days(1), -4,
          first_scanned_at=now - _hours(20), last_tracking_update_at=now - _hours(18)),
        # Belongs to another customer (cross-customer access test)
        o(OTHER_CUSTOMER_EMAIL, "SP-3001", OrderStatus.DELIVERED, S, "Board game", 950, 2800,
          now - _days(8), 3, first_scanned_at=now - _days(7), delivered_at=now - _days(3),
          last_tracking_update_at=now - _days(3)),
    ]


def filler_specs(rng: random.Random, now: datetime) -> list[tuple[str, dict]]:
    """Deterministic background orders spread across all customers."""
    emails = [email for _, email in CUSTOMERS]
    specs: list[tuple[str, dict]] = []

    for i in range(FILLER_COUNT):
        email = emails[i % len(emails)]
        number = f"SP-{2001 + i}"
        status = rng.choices(FILLER_STATUSES, weights=FILLER_WEIGHTS)[0]
        level = rng.choice(FILLER_LEVELS)
        if status == OrderStatus.DELAYED and level == ServiceLevel.EXPRESS:
            level = ServiceLevel.STANDARD
        transit = SERVICE_DAYS[level]
        fee = rng.choice(FEES)
        declared = rng.choice(DECLARED_VALUES)
        description = rng.choice(ITEMS)
        jitter = _hours(rng.randint(0, 5))
        extra: dict = {}

        if status == OrderStatus.PLACED:
            created = now - _hours(rng.randint(1, 20))
        elif status == OrderStatus.PROCESSING:
            created = now - _days(1) - jitter
            extra["last_tracking_update_at"] = created + _hours(1)
        elif status == OrderStatus.SHIPPED:
            created = now - _days(1) - jitter
            extra["first_scanned_at"] = created + _hours(3)
            extra["last_tracking_update_at"] = created + _hours(3)
        elif status == OrderStatus.IN_TRANSIT:
            created = now - _days(rng.randint(1, max(1, transit - 1))) - jitter
            scanned = created + _hours(3)
            extra["first_scanned_at"] = scanned
            extra["last_tracking_update_at"] = max(scanned, now - _hours(rng.randint(2, 30)))
        elif status == OrderStatus.OUT_FOR_DELIVERY:
            created = now - _days(transit)
            extra["first_scanned_at"] = created + _hours(3)
            extra["last_tracking_update_at"] = now - _hours(rng.randint(1, 3))
        elif status == OrderStatus.DELIVERED:
            created = now - _days(transit + rng.randint(3, 40)) - jitter
            delivered = datetime.combine((created + _days(transit)).date(), time(14, 0))
            extra["first_scanned_at"] = created + _hours(3)
            extra["delivered_at"] = delivered
            extra["last_tracking_update_at"] = delivered
        elif status == OrderStatus.DELAYED:
            created = now - _days(transit + rng.randint(2, 4)) - jitter
            extra["first_scanned_at"] = created + _hours(3)
            extra["last_tracking_update_at"] = now - _days(1)
            extra["delay_reason"] = DelayReason.OTHER
        else:  # CANCELLED
            created = now - _days(rng.randint(2, 15)) - jitter
            if rng.random() < 0.5:
                extra["first_scanned_at"] = created + _hours(3)
                extra["cancelled_at"] = created + _hours(6)
            else:
                extra["cancelled_at"] = created + _hours(2)
            extra["last_tracking_update_at"] = extra["cancelled_at"]

        est_days_ago = (now.date() - (created + _days(transit)).date()).days
        specs.append((
            email,
            _order_kwargs(
                now, number=number, status=status, level=level, description=description,
                fee=fee, declared=declared, created=created, est_days_ago=est_days_ago, **extra,
            ),
        ))
    return specs


def _refund_seeds(now: datetime) -> list[dict]:
    return [
        dict(reference="RR-SEED0001", order="SP-1010", reason=RefundReason.CANCELLED,
             status=RefundStatus.APPROVED, amount=1200, approval=False, photos=0,
             rule="CANCELLED_FULL_FEE", note="Cancelled before the first scan.",
             created=now - _days(2)),
        dict(reference="RR-SEED0002", order="SP-1008", reason=RefundReason.LOST,
             status=RefundStatus.PENDING_REVIEW, amount=9800, approval=True, photos=0,
             rule="LOST_CONFIRMED", note=None, created=now - _days(3)),
        dict(reference="RR-SEED0003", order="SP-1018", reason=RefundReason.OTHER,
             status=RefundStatus.REJECTED, amount=899, approval=False, photos=0,
             rule="NO_QUALIFYING_REASON", note="Changed my mind.", created=now - _days(8)),
    ]


def _ticket_seeds(now: datetime) -> list[dict]:
    return [
        dict(reference="TK-SEED0001", email=DEMO_CUSTOMER_EMAIL, order="SP-1009",
             category=TicketCategory.DELIVERY_ISSUE, status=TicketStatus.OPEN,
             subject="Parcel has not moved for several days",
             description="Tracking has shown no update for over a week.", created=now - _days(1)),
        dict(reference="TK-SEED0002", email=DEMO_CUSTOMER_EMAIL, order="SP-1018",
             category=TicketCategory.REFUND, status=TicketStatus.RESOLVED,
             subject="Question about returning my order",
             description="Asked whether a delivered order could be refunded.", created=now - _days(9)),
        dict(reference="TK-SEED0003", email=OTHER_CUSTOMER_EMAIL, order="SP-3001",
             category=TicketCategory.COMPLAINT, status=TicketStatus.OPEN,
             subject="Driver left the parcel in the rain",
             description="Packaging was soaked on arrival.", created=now - _days(2)),
    ]


def _ensure_customers(session: Session) -> tuple[dict[str, Customer], int]:
    existing = {c.email: c for c in session.scalars(select(Customer))}
    created = 0
    for name, email in CUSTOMERS:
        if email not in existing:
            existing[email] = Customer(name=name, email=email)
            session.add(existing[email])
            created += 1
    session.flush()
    return existing, created


def _ensure_orders(session: Session, customers: dict[str, Customer], specs: list[tuple[str, dict]]) -> int:
    existing = set(session.scalars(select(Order.order_number)))
    created = 0
    for email, kwargs in specs:
        if kwargs["order_number"] in existing:
            continue
        session.add(Order(customer_id=customers[email].id, **kwargs))
        created += 1
    session.flush()
    return created


def _ensure_refunds(session: Session, seeds: list[dict]) -> int:
    orders = {o.order_number: o for o in session.scalars(select(Order))}
    existing = set(session.scalars(select(RefundRequest.reference)))
    created = 0
    for s in seeds:
        if s["reference"] in existing:
            continue
        order = orders[s["order"]]
        session.add(RefundRequest(
            reference=s["reference"], order_id=order.id, customer_id=order.customer_id,
            reason=s["reason"], status=s["status"], amount_cents=s["amount"],
            requires_support_approval=s["approval"], evidence_photo_count=s["photos"],
            rule_code=s["rule"], customer_note=s["note"],
            created_at=s["created"], updated_at=s["created"],
        ))
        created += 1
    session.flush()
    return created


def _ensure_tickets(session: Session, customers: dict[str, Customer], seeds: list[dict]) -> int:
    orders = {o.order_number: o for o in session.scalars(select(Order))}
    existing = set(session.scalars(select(SupportTicket.reference)))
    created = 0
    for s in seeds:
        if s["reference"] in existing:
            continue
        session.add(SupportTicket(
            reference=s["reference"], customer_id=customers[s["email"]].id,
            order_id=orders[s["order"]].id, category=s["category"], status=s["status"],
            subject=s["subject"], description=s["description"],
            created_at=s["created"], updated_at=s["created"],
        ))
        created += 1
    session.flush()
    return created


def seed(reset: bool = False) -> dict[str, int]:
    if reset:
        Base.metadata.drop_all(engine)
    init_db()

    now = utcnow().replace(second=0, microsecond=0)
    rng = random.Random(RNG_SEED)
    order_specs = scenario_specs(now) + filler_specs(rng, now)

    with SessionLocal() as session:
        customers, new_customers = _ensure_customers(session)
        new_orders = _ensure_orders(session, customers, order_specs)
        new_refunds = _ensure_refunds(session, _refund_seeds(now))
        new_tickets = _ensure_tickets(session, customers, _ticket_seeds(now))
        session.commit()

        def total(model) -> int:
            return session.scalar(select(func.count()).select_from(model))

        return {
            "customers_created": new_customers,
            "orders_created": new_orders,
            "refund_requests_created": new_refunds,
            "tickets_created": new_tickets,
            "customers_total": total(Customer),
            "orders_total": total(Order),
            "refund_requests_total": total(RefundRequest),
            "tickets_total": total(SupportTicket),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed synthetic demo data into SQLite.")
    parser.add_argument("--reset", action="store_true", help="Drop all tables and re-seed.")
    args = parser.parse_args()
    print(seed(reset=args.reset))
    print(f"Demo customer: {DEMO_CUSTOMER_EMAIL}")


if __name__ == "__main__":
    main()