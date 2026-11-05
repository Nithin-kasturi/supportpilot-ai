import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import settings


class SlidingWindowLimiter:
    """In-memory, per process. Resets on restart; a multi-worker deployment needs a shared store."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] >= window_seconds:
                events.popleft()
            if len(events) >= limit:
                return False, int(window_seconds - (now - events[0])) + 1
            events.append(now)
            if len(self._events) > 10_000:
                for stale in [k for k, v in self._events.items() if not v]:
                    del self._events[stale]
            return True, 0


LIMITER = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"