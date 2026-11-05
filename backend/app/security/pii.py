"""PII and secret masking. Regex-based and best-effort: it reduces exposure, it is not a guarantee."""

import re

_JWT = re.compile(r"\beyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]{5,}\b")
_BEARER = re.compile(r"(?i)\bbearer\s+[\w.~+/=-]+")
_SECRET_KV = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\b(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"(?<![\w-])(?:\d[ -]?){13,19}(?![\w-])")
_PHONE = re.compile(r"(?<![\w-])\+?\d[\d\s().-]{8,}\d(?![\w-])")


def redact_secrets(text: str) -> str:
    text = _JWT.sub("[token]", text)
    text = _BEARER.sub("Bearer [token]", text)
    return _SECRET_KV.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)


def mask_pii(text: str) -> str:
    """Mask secrets, emails, phone numbers, card and national-id-like numbers. Order numbers (SP-1004) survive."""
    text = redact_secrets(text)
    text = _SSN.sub("[ssn]", text)
    text = _CARD.sub("[card number]", text)
    text = _EMAIL.sub("[email]", text)
    return _PHONE.sub("[phone]", text)


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"