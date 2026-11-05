"""Controls around the LLM. These are layers, not guarantees: the real protections are architectural
(identity from the token, permissions and ownership in backend code, deterministic eligibility,
server-side confirmation). Heuristics here only reduce noise and catch obvious leaks."""

import re
import secrets
import unicodedata
from collections.abc import Callable, Iterable
from typing import TypeVar

from app.security.pii import redact_secrets

T = TypeVar("T")

# Per-process secret marker embedded in the system prompt. If it ever appears in a reply, the prompt leaked.
CANARY = f"SPK-{secrets.token_hex(8)}"

_INVISIBLE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]"
)
_INSTRUCTION_LIKE = [
    re.compile(p, re.I | re.M)
    for p in (
        r"ignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier) (?:instructions|rules|messages)",
        r"disregard (?:all |any )?(?:the )?(?:previous|prior|above|your) (?:instructions|rules)",
        r"\byou (?:must|should|will) now\b",
        r"\b(?:system|developer) (?:prompt|message|instructions?)\b",
        r"</?(?:tool_results|policy_context|system|assistant|user)>",
        r"^\s*(?:assistant|system|user)\s*:",
        r"\b(?:reveal|print|show|output|repeat) (?:your|the) (?:instructions|prompt|secret|key|token)\b",
        r"\bapprove (?:the |this |every |all |any )?refunds?\b",
    )
]
LEAK_REFUSAL = (
    "I can't share internal instructions or configuration. I'm happy to help with your parcels, "
    "orders, refunds or complaints."
)


def sanitize_user_text(text: str) -> str:
    """Normalise and strip control and bidi/zero-width characters (used to hide instructions)."""
    return _INVISIBLE.sub("", unicodedata.normalize("NFKC", text)).strip()


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _leaks_prompt(reply: str, prompts: Iterable[str]) -> bool:
    normalised = _normalise(reply)
    for prompt in prompts:
        for line in prompt.splitlines():
            line = _normalise(line.lstrip("-• "))
            if len(line) >= 40 and line in normalised:
                return True
    return False


def filter_reply(reply: str, system_prompts: Iterable[str]) -> str:
    """Block prompt/canary leaks and strip token-like strings from model output."""
    if CANARY in reply or _leaks_prompt(reply, system_prompts):
        return LEAK_REFUSAL
    return redact_secrets(reply)


def screen_chunks(chunks: list[T], text_of: Callable[[T], str] | None = None, id_of: Callable[[T], str] | None = None) -> tuple[list[T], list[str]]:
    """Quarantine retrieved chunks that read like instructions (indirect prompt injection).

    Kept chunks are still delimited as reference data and never treated as instructions."""
    text_of = text_of or (lambda c: c.text)  # type: ignore[attr-defined]
    id_of = id_of or (lambda c: c.chunk_id)  # type: ignore[attr-defined]
    kept: list[T] = []
    quarantined: list[str] = []
    for chunk in chunks:
        if any(pattern.search(text_of(chunk)) for pattern in _INSTRUCTION_LIKE):
            quarantined.append(id_of(chunk))
        else:
            kept.append(chunk)
    return kept, quarantined