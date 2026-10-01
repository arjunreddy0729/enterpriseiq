"""Per-client rate limits for the public demo.

A sliding-window counter held in process memory. That is the right size for
this deployment, which is one container: no Redis to run, nothing to pay for,
and a restart simply forgets the windows. It is the wrong design for several
replicas, where each would keep its own count and the effective limit would
multiply; at that point the counters belong in Redis or Postgres.

The client is identified by IP address. Behind a reverse proxy the socket
address is the proxy's, so the address comes from X-Forwarded-For instead,
taken at a fixed position from the RIGHT (see Settings.forwarded_proxy_hops).
Entries further left were written by the client and cannot be trusted; reading
the leftmost one would let anyone pick a fresh "IP" per request.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings


class SlidingWindowLimiter:
    """At most `limit` hits per `window_seconds`, per key."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def hit(self, key: str, limit: int, window_seconds: float) -> float | None:
        """Record a hit. Returns None if allowed, else seconds until retry."""
        now = self._clock()
        cutoff = now - window_seconds
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return max(hits[0] + window_seconds - now, 0.0)
            hits.append(now)
            self._calls += 1
            if self._calls % 1000 == 0:
                self._prune(cutoff)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _prune(self, cutoff: float) -> None:
        """Drop keys with no recent hits so memory tracks active clients only.
        Uses the current call's cutoff, which is conservative for any longer
        window: such a key is pruned only if it would be empty here too."""
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]


limiter = SlidingWindowLimiter()


def client_address(request: Request, proxy_hops: int) -> str:
    return address_from(
        request.headers, request.client.host if request.client else None, proxy_hops
    )


def address_from(headers: Mapping[str, str], peer: str | None, proxy_hops: int) -> str:
    """The client's address: the proxy's entry in X-Forwarded-For when behind
    `proxy_hops` proxies, else the socket peer."""
    if proxy_hops > 0:
        forwarded = [
            part.strip() for part in headers.get("x-forwarded-for", "").split(",") if part.strip()
        ]
        if len(forwarded) >= proxy_hops:
            return forwarded[-proxy_hops]
    return peer or "unknown"


def rate_limit(
    bucket: str, limit_of: Callable[[Settings], int], window_seconds: float
) -> Callable[..., None]:
    """A FastAPI dependency enforcing one named limit."""

    def dependency(request: Request, settings: Settings = Depends(get_settings)) -> None:
        if not settings.rate_limits_active:
            return
        key = f"{bucket}:{client_address(request, settings.forwarded_proxy_hops)}"
        retry_after = limiter.hit(key, limit_of(settings), window_seconds)
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many {bucket} requests. Try again in {math.ceil(retry_after)}s.",
                headers={"Retry-After": str(math.ceil(retry_after))},
            )

    return dependency


login_limit = rate_limit("login", lambda s: s.rate_limit_login_per_minute, 60)
search_limit = rate_limit("search", lambda s: s.rate_limit_search_per_minute, 60)
query_limit = rate_limit("query", lambda s: s.rate_limit_query_per_hour, 3600)
