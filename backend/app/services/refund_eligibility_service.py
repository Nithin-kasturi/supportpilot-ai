"""Deterministic refund eligibility. This is the ONLY place refund rules live.

Rules mirror the policy documents in data/policies/. The LLM never decides eligibility; it may
only explain the structured result. Money is in integer cents. No database access happens here.
"""

from datetime import date, datetime, timedelta

from app.database.session import utcnow
from app.models import DelayReason, ExceptionReason, Order, OrderStatus, RefundReason, ServiceLevel
from app.schemas.refunds import EligibilityResult

# Refund Policy - Approval thresholds: under $50.00 can be automatic; $50.00 or more needs approval.
AUTO_APPROVAL_LIMIT_CENTS = 5_000
# Refund Policy: declared item value is capped at $500.00 per parcel.
DECLARED_VALUE_CAP_CENTS = 50_000
# Refund Policy - Refund request time limit: 30 calendar days.
REQUEST_WINDOW_DAYS = 30
# Damaged Parcel Policy: report within 48 hours; at least 2 photographs.
DAMAGE_REPORT_WINDOW = timedelta(hours=48)
MIN_DAMAGE_PHOTOS = 2
# Shipping Policy: potentially lost after 7 days without a tracking update; delayed after 2 business days.
LOST_NO_UPDATE = timedelta(days=7)
LATE_BUSINESS_DAYS = 2
# Cancellation Policy fees.
RETURN_HANDLING_FEE_CENTS = 500
LATE_PICKUP_CANCEL_FEE_CENTS = 300
PICKUP_CANCEL_NOTICE = timedelta(hours=2)

P_REFUND_REASONS = "Refund Policy - Eligible refund reasons"
P_NON_REFUNDABLE = "Refund Policy - Non-refundable situations"
P_REQUEST_LIMIT = "Refund Policy - Refund request time limit"
P_APPROVAL = "Refund Policy - Approval thresholds"
P_DAMAGE_DEADLINE = "Damaged Parcel Policy - Reporting deadline"
P_DAMAGE_EVIDENCE = "Damaged Parcel Policy - Required evidence"
P_DAMAGE_APPROVAL = "Damaged Parcel Policy - Approval by order value"
P_SHIP_DELAYED = "Shipping Policy - Delayed parcels"
P_SHIP_LOST = "Shipping Policy - Lost parcels"
P_CANCEL_BEFORE = "Cancellation Policy - Cancellation before first scan"
P_CANCEL_AFTER = "Cancellation Policy - Cancellation after first scan"
P_CANCEL_PICKUP = "Cancellation Policy - Scheduled pickups"
P_CANCEL_OUT = "Cancellation Policy - Out for delivery or delivered"

TICKET_HINT = "If you believe this is wrong or need more help, create a support ticket for this order."
AUTO_NEXT = (
    "You can submit a refund request. It can be approved automatically, and approved refunds are "
    "paid to the original payment method within 5 to 7 business days."
)
REVIEW_NEXT = (
    "You can submit a refund request. The support team will review it and decide within 3 business days."
)

_EXCLUSION_TEXT = {
    ExceptionReason.INCORRECT_ADDRESS: "the delivery failed because of an incorrect or incomplete address supplied by the customer.",
    ExceptionReason.RECIPIENT_REFUSED: "the recipient refused the delivery.",
    ExceptionReason.UNCLAIMED_AT_DEPOT: "the parcel was not claimed within the 7-day depot holding period.",
    ExceptionReason.PROHIBITED_ITEM: "the parcel contained a prohibited item.",
}


def usd(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def add_business_days(start: date, days: int) -> date:
    """Monday to Friday only. Public holidays are not modelled."""
    current, remaining = start, days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _build(
    order: Order,
    reason: RefundReason,
    *,
    eligible: bool | None,
    text: str,
    policy: list[str],
    rule: str,
    next_action: str,
    amount: int | None = None,
    approval: bool = False,
) -> EligibilityResult:
    return EligibilityResult(
        order_number=order.order_number,
        refund_reason=reason,
        eligible=eligible,
        reason=text,
        applicable_policy="; ".join(policy),
        requires_support_approval=approval,
        next_action=next_action,
        refundable_amount_cents=amount,
        rule_code=rule,
    )


def _not_eligible(order, reason, *, text, policy, rule, next_action=TICKET_HINT) -> EligibilityResult:
    return _build(order, reason, eligible=False, text=text, policy=policy, rule=rule, next_action=next_action)


def _manual_review(order, reason, *, text, policy, rule, next_action, amount=None) -> EligibilityResult:
    return _build(
        order, reason, eligible=None, text=text, policy=policy, rule=rule,
        next_action=next_action, amount=amount, approval=True,
    )


def _eligible(order, reason, *, text, policy, rule, amount) -> EligibilityResult:
    approval = amount >= AUTO_APPROVAL_LIMIT_CENTS
    return _build(
        order, reason, eligible=True, text=text, policy=policy + [P_APPROVAL], rule=rule,
        next_action=REVIEW_NEXT if approval else AUTO_NEXT, amount=amount, approval=approval,
    )


def _refundable_with_value(order: Order) -> int:
    return order.shipping_fee_cents + min(order.declared_value_cents, DECLARED_VALUE_CAP_CENTS)


def _breakdown(order: Order) -> str:
    value = min(order.declared_value_cents, DECLARED_VALUE_CAP_CENTS)
    return f"shipping fee {usd(order.shipping_fee_cents)} plus declared value {usd(value)}"


# ---------------------------------------------------------------------------------------------
# Rules per refund reason
# ---------------------------------------------------------------------------------------------


def _check_billing(order: Order) -> EligibilityResult:
    return _manual_review(
        order, RefundReason.BILLING_ERROR,
        text="Billing errors such as duplicate charges cannot be verified from order data, so they need manual review.",
        policy=[P_REFUND_REASONS], rule="BILLING_NEEDS_REVIEW",
        next_action="Create a support ticket describing the charge so the team can verify it.",
    )


def _check_excluded(order: Order, reason: RefundReason) -> EligibilityResult:
    exc = order.exception_reason
    return _not_eligible(
        order, reason,
        text=f"This order is in a non-refundable situation: {_EXCLUSION_TEXT[exc]}",
        policy=[P_NON_REFUNDABLE], rule=f"EXCLUDED_{exc.name}",
    )


def _check_cancelled(order: Order, now: datetime) -> EligibilityResult:
    r = RefundReason.CANCELLED
    if order.status == OrderStatus.DELIVERED or order.delivered_at is not None:
        return _not_eligible(order, r, rule="CANCEL_DELIVERED", policy=[P_CANCEL_OUT],
                             text="The order has already been delivered, so it cannot be cancelled.")
    if order.status == OrderStatus.OUT_FOR_DELIVERY:
        return _not_eligible(order, r, rule="CANCEL_OUT_FOR_DELIVERY", policy=[P_CANCEL_OUT],
                             text="The parcel is out for delivery, and an order cannot be cancelled at this stage.")
    if order.status == OrderStatus.LOST:
        return _not_eligible(order, r, rule="CANCEL_ORDER_LOST", policy=[P_REFUND_REASONS],
                             text="This order is recorded as lost. Use the lost-parcel refund reason instead.")
    if order.status != OrderStatus.CANCELLED or order.cancelled_at is None:
        return _not_eligible(
            order, r, rule="CANCEL_NOT_CANCELLED", policy=[P_REFUND_REASONS],
            text="The order has not been cancelled. A cancellation refund applies only once the order is cancelled.",
            next_action="To cancel this order, create a support ticket asking support to cancel it, then check again.",
        )
    if (now.date() - order.estimated_delivery_date).days > REQUEST_WINDOW_DAYS:
        return _not_eligible(order, r, rule="CANCEL_WINDOW_EXPIRED", policy=[P_REQUEST_LIMIT],
                             text="The 30-day refund request limit has passed.")

    fee_total = order.shipping_fee_cents
    scanned = order.first_scanned_at is not None and order.first_scanned_at <= order.cancelled_at
    if scanned:
        fee, rule, policy = RETURN_HANDLING_FEE_CENTS, "CANCELLED_AFTER_SCAN_FEE", [P_CANCEL_AFTER]
        detail = f"cancelled after its first scan, so a {usd(fee)} return handling fee is deducted"
    elif order.pickup_window_start is not None and order.cancelled_at > order.pickup_window_start - PICKUP_CANCEL_NOTICE:
        # Specific rule wins over the general "no fee before first scan" statement.
        fee, rule, policy = LATE_PICKUP_CANCEL_FEE_CENTS, "CANCELLED_LATE_PICKUP_FEE", [P_CANCEL_PICKUP]
        detail = f"cancelled less than 2 hours before its pickup window, so a {usd(fee)} late-cancellation fee is deducted"
    else:
        fee, rule, policy = 0, "CANCELLED_FULL_FEE", [P_CANCEL_BEFORE]
        detail = "cancelled before its first scan, so there is no cancellation fee"

    amount = max(0, fee_total - fee)
    if amount == 0:
        return _not_eligible(order, r, rule="CANCEL_NO_REFUNDABLE_AMOUNT", policy=policy,
                             text="The cancellation fees equal or exceed the shipping fee, so nothing is refundable.")
    text = f"The order was {detail}. Refundable amount: {usd(amount)} (shipping fee {usd(fee_total)})."
    return _eligible(order, r, text=text, policy=policy, rule=rule, amount=amount)


def _check_late_express(order: Order, now: datetime) -> EligibilityResult:
    r = RefundReason.LATE_EXPRESS
    if order.service_level != ServiceLevel.EXPRESS:
        return _not_eligible(
            order, r, rule="LATE_NOT_EXPRESS", policy=[P_SHIP_DELAYED, P_NON_REFUNDABLE],
            text="Late Standard and Economy deliveries do not receive automatic compensation. Support can investigate.",
        )
    if order.status in (OrderStatus.CANCELLED, OrderStatus.LOST):
        return _not_eligible(order, r, rule="LATE_NOT_APPLICABLE", policy=[P_SHIP_DELAYED],
                             text="This order was cancelled or is recorded as lost. Use the matching refund reason instead.")

    deadline = add_business_days(order.estimated_delivery_date, LATE_BUSINESS_DAYS)
    arrival = (order.delivered_at or now).date()
    if arrival <= deadline:
        if order.delivered_at is not None:
            return _not_eligible(order, r, rule="LATE_NOT_DELAYED", policy=[P_SHIP_DELAYED],
                                 text="The parcel arrived within 2 business days of its estimated delivery date, so it is not delayed.")
        return _not_eligible(
            order, r, rule="LATE_NOT_YET_DELAYED", policy=[P_SHIP_DELAYED],
            text=f"The parcel is not yet delayed. It counts as delayed if it has not arrived after {deadline.isoformat()}.",
            next_action="Check again after that date if the parcel has still not arrived.",
        )
    if order.delay_reason == DelayReason.WEATHER:
        return _not_eligible(order, r, rule="LATE_WEATHER_EXCLUDED", policy=[P_SHIP_DELAYED],
                             text="The delay was caused by severe weather, which does not qualify for the Express shipping fee refund.")
    if order.delay_reason is None:
        return _manual_review(
            order, r, rule="LATE_CAUSE_UNKNOWN", policy=[P_SHIP_DELAYED], amount=order.shipping_fee_cents,
            text="The parcel is delayed, but the cause is not recorded, so the weather exclusion cannot be checked.",
            next_action="Create a support ticket so the team can confirm the cause of the delay.",
        )
    reference = order.delivered_at.date() if order.delivered_at else order.estimated_delivery_date
    if (now.date() - reference).days > REQUEST_WINDOW_DAYS:
        return _not_eligible(order, r, rule="LATE_WINDOW_EXPIRED", policy=[P_REQUEST_LIMIT],
                             text="The 30-day refund request limit has passed.")
    amount = order.shipping_fee_cents
    text = f"The Express parcel is delayed beyond 2 business days. The shipping fee of {usd(amount)} is refundable (not the declared value)."
    return _eligible(order, r, text=text, policy=[P_SHIP_DELAYED], rule="LATE_EXPRESS_ELIGIBLE", amount=amount)


def _check_lost(order: Order, now: datetime) -> EligibilityResult:
    r = RefundReason.LOST
    if order.status == OrderStatus.LOST:
        if (now.date() - order.estimated_delivery_date).days > REQUEST_WINDOW_DAYS:
            return _not_eligible(order, r, rule="LOST_WINDOW_EXPIRED", policy=[P_REQUEST_LIMIT],
                                 text="The 30-day refund request limit has passed.")
        amount = _refundable_with_value(order)
        text = f"The parcel is confirmed lost. Refundable amount: {usd(amount)} ({_breakdown(order)})."
        return _eligible(order, r, text=text, policy=[P_SHIP_LOST], rule="LOST_CONFIRMED", amount=amount)

    if order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED) or order.delivered_at is not None:
        return _not_eligible(order, r, rule="LOST_NOT_APPLICABLE", policy=[P_SHIP_LOST],
                             text="This order was delivered or cancelled, so it cannot be a lost parcel.")

    last_event = order.last_tracking_update_at or order.created_at
    if now - last_event >= LOST_NO_UPDATE:
        return _manual_review(
            order, r, rule="LOST_POSSIBLE", policy=[P_SHIP_LOST],
            text="Tracking has not updated for 7 days or more, so the parcel may be lost. It is not confirmed lost yet.",
            next_action="Create a support ticket to start a lost-parcel investigation (up to 5 business days).",
        )
    return _not_eligible(
        order, r, rule="LOST_TOO_EARLY", policy=[P_SHIP_LOST],
        text="Tracking has updated within the last 7 days, so the parcel cannot be reported as potentially lost yet.",
        next_action="Check again if tracking shows no update for 7 days.",
    )


def _check_damaged(order: Order, photos: int, now: datetime) -> EligibilityResult:
    r = RefundReason.DAMAGED
    if order.status != OrderStatus.DELIVERED or order.delivered_at is None:
        return _not_eligible(order, r, rule="DAMAGE_NOT_DELIVERED", policy=[P_DAMAGE_DEADLINE],
                             text="Damage can only be reported after the parcel has been delivered.")
    elapsed = now - order.delivered_at
    if elapsed > DAMAGE_REPORT_WINDOW:
        hours = int(elapsed.total_seconds() // 3600)
        return _not_eligible(
            order, r, rule="DAMAGE_WINDOW_EXPIRED", policy=[P_DAMAGE_DEADLINE],
            text=f"The parcel was delivered about {hours} hours ago. Damage must be reported within 48 hours of delivery.",
            next_action="If a documented SwiftParcel system fault prevented you from reporting in time, create a support ticket.",
        )
    amount = _refundable_with_value(order)
    if photos < MIN_DAMAGE_PHOTOS:
        return _manual_review(
            order, r, rule="DAMAGE_EVIDENCE_INCOMPLETE", policy=[P_DAMAGE_EVIDENCE, P_DAMAGE_APPROVAL], amount=amount,
            text=f"A damage claim needs at least 2 clear photographs; {photos} provided. It cannot be approved until the evidence is complete.",
            next_action="Provide at least 2 photographs (the damaged item, and the outer packaging showing the shipping label) within 3 business days of reporting.",
        )
    text = (
        f"The damage was reported within 48 hours and the evidence is complete. Refundable amount: {usd(amount)} "
        f"({_breakdown(order)}). Final approval remains subject to the exclusions in the Damaged Parcel Policy "
        "(for example inadequate packaging or pre-existing damage)."
    )
    return _eligible(order, r, text=text, policy=[P_DAMAGE_DEADLINE, P_DAMAGE_EVIDENCE, P_DAMAGE_APPROVAL],
                     rule="DAMAGE_ELIGIBLE", amount=amount)


def _check_other(order: Order) -> EligibilityResult:
    return _not_eligible(
        order, RefundReason.OTHER, rule="NO_QUALIFYING_REASON", policy=[P_REFUND_REASONS, P_NON_REFUNDABLE],
        text="A refund applies only for a cancelled order, a late Express delivery, a lost parcel, an approved damage claim or a billing error. A change of mind after delivery is not refundable.",
    )


# ---------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------


def check_eligibility(
    order: Order,
    reason: RefundReason,
    evidence_photo_count: int = 0,
    now: datetime | None = None,
) -> EligibilityResult:
    now = now or utcnow()

    if reason == RefundReason.BILLING_ERROR:
        return _check_billing(order)
    if order.exception_reason is not None:
        return _check_excluded(order, reason)

    if reason == RefundReason.CANCELLED:
        return _check_cancelled(order, now)
    if reason == RefundReason.LATE_EXPRESS:
        return _check_late_express(order, now)
    if reason == RefundReason.LOST:
        return _check_lost(order, now)
    if reason == RefundReason.DAMAGED:
        return _check_damaged(order, evidence_photo_count, now)
    return _check_other(order)