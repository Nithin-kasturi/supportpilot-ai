"""Deterministic extraction. Entities that drive tools come from here, not from free-form LLM output."""

import re

from app.agent.state import Intent
from app.models import RefundReason, TicketCategory

_ORDER_RE = re.compile(r"\bSP[-\s]?(\d{3,6})\b", re.I)
_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_NUM = r"(\d{1,2}|zero|one|two|three|four|five|six|seven|eight|nine|ten)"
_PHOTO_RE = re.compile(rf"\b{_NUM}\s+(?:clear\s+|good\s+)?(?:photos?|pictures?|images?|pics?)\b", re.I)
_NO_PHOTO_RE = re.compile(r"\b(?:no|without any)\s+(?:photos?|pictures?|images?|pics?)\b", re.I)
_BARE_NUMBER_RE = re.compile(rf"^\W*{_NUM}\W*$", re.I)
_NONE_RE = re.compile(r"^\W*(?:none|no|nope)\W*$", re.I)

_REASON_PATTERNS: list[tuple[RefundReason, re.Pattern[str]]] = [
    (RefundReason.DAMAGED, re.compile(r"damag|broken|cracked|smashed|crushed|torn", re.I)),
    (RefundReason.LATE_EXPRESS, re.compile(r"\blate\b|delay|overdue|not on time", re.I)),
    (RefundReason.LOST, re.compile(r"\blost\b|never arrived|missing|didn'?t arrive", re.I)),
    (RefundReason.CANCELLED, re.compile(r"cancel", re.I)),
    (
        RefundReason.BILLING_ERROR,
        re.compile(r"billing|charged twice|double charge|duplicate charge|overcharg", re.I),
    ),
]
_CATEGORY_PATTERNS: list[tuple[TicketCategory, re.Pattern[str]]] = [
    (TicketCategory.DAMAGED_PARCEL, re.compile(r"damag|broken|cracked|crushed", re.I)),
    (TicketCategory.REFUND, re.compile(r"refund|money back|charged", re.I)),
    (TicketCategory.CANCELLATION, re.compile(r"cancel", re.I)),
    (TicketCategory.COMPLAINT, re.compile(r"complain|rude|unacceptable|misconduct", re.I)),
    (
        TicketCategory.DELIVERY_ISSUE,
        re.compile(r"deliver|late|lost|missing|track|arriv|stuck|where", re.I),
    ),
]


def parse_order_number(text: str) -> str | None:
    match = _ORDER_RE.search(text)
    return f"SP-{match.group(1)}" if match else None


def _to_int(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS[token.lower()]


def parse_photos(text: str, allow_bare: bool = False) -> int | None:
    match = _PHOTO_RE.search(text)
    if match:
        return min(_to_int(match.group(1)), 20)
    if _NO_PHOTO_RE.search(text):
        return 0
    if allow_bare:
        if _NONE_RE.match(text):
            return 0
        bare = _BARE_NUMBER_RE.match(text)
        if bare:
            return min(_to_int(bare.group(1)), 20)
    return None


def parse_reason(text: str) -> RefundReason | None:
    for reason, pattern in _REASON_PATTERNS:
        if pattern.search(text):
            return reason
    return None


def parse_category(text: str) -> TicketCategory:
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(text):
            return category
    return TicketCategory.OTHER


def heuristic_intent(message: str) -> Intent:
    """Fallback when the LLM's JSON cannot be used. Never picks a creation intent from a question."""
    text = message.lower()
    has_order = parse_order_number(message) is not None
    if re.fullmatch(r"\W*(hi|hello|hey|thanks|thank you|bye|good (morning|afternoon|evening))\W*", text):
        return Intent.CHITCHAT
    if re.search(r"\b(open|create|raise|file|submit|make)\b.*\b(ticket|complaint)\b", text):
        return Intent.TICKET_REQUEST
    if re.search(r"\b(submit|create|file|open|raise|start)\b.*\brefund\b", text) and not re.search(
        r"\b(can|could|am i|eligible|how)\b", text
    ):
        return Intent.REFUND_REQUEST
    if "refund" in text and (has_order or "eligible" in text):
        return Intent.REFUND_ELIGIBILITY
    if re.search(r"\b(my orders|recent orders|order history|list (of )?(my )?orders)\b", text):
        return Intent.LIST_ORDERS
    if has_order and re.search(r"\b(where|status|track|tracking|delivered|arrive|when)\b", text):
        return Intent.ORDER_STATUS
    if re.search(r"\b(refund|damaged|delivery|shipping|cancel|policy|escalat|complain|late|lost)\b", text):
        return Intent.POLICY
    return Intent.OFF_TOPIC