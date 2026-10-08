"""In-process sliding-window rate limiting.

Complements the per-account lockout (services/auth.py): the lockout throttles
guesses against one account, this throttles one client across many accounts
and floods of public endpoints. State is per process; the Render deployment
runs a single web instance (see render.yaml). If the API is ever scaled out,
move this to a shared store.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.config import get_settings


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= now - window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            if len(self._hits) > 50_000:  # bound memory under a flood of distinct keys
                for stale in [k for k, v in self._hits.items() if not v][:10_000]:
                    del self._hits[stale]
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    """The caller's address. Behind the host's load balancer ``X-Forwarded-For`` is
    ``<whatever the client sent>, <address the load balancer saw>``: everything to the left
    of the trusted proxies' entries is client-controlled, so the address is counted from the
    right (``TRUSTED_PROXY_COUNT`` hops, 1 on Render) rather than read from the left, which
    would let anyone pick a fresh "IP" per request and dodge every rate limit."""
    settings = get_settings()
    if settings.trust_proxy_headers:
        hops = [hop.strip() for hop in request.headers.get("x-forwarded-for", "").split(",") if hop.strip()]
        if len(hops) >= settings.trusted_proxy_count:
            return hops[-settings.trusted_proxy_count]
    return request.client.host if request.client else "unknown"


def rate_limit(name: str, limit: int, window_seconds: int = 60):
    """FastAPI dependency: ``Depends(rate_limit("login", 10))``."""

    def dependency(request: Request) -> None:
        if not limiter.hit(f"{name}:{client_ip(request)}", limit, window_seconds):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please wait a moment and try again.",
            )

    return dependency
