"""
In-memory sliding-window rate limiter for the local advisory MVP.

Why this module exists separately from ``scripts.api_server``:

- The limiter is the kind of code that is easy to get wrong silently.
  Putting it in a standalone module lets ``tests/test_rate_limiter.py``
  exercise the bucket logic directly without needing FastAPI or a running
  server.
- Pure Python stdlib only.  No Redis.  No external dependency.  This is
  deliberate: the MVP runs on a single laptop and a hosted deployment is
  out of scope for the current sprint.  When the system grows past
  "one user on localhost" the right move is to put a reverse proxy in
  front (rate limit there) rather than to bolt distributed state onto
  this module.

The limiter is sliding-window: each client_key keeps a deque of
timestamps of its recent requests, and a request is allowed iff the
deque has fewer than ``max_requests`` entries inside the trailing
``window_seconds``.  This is more accurate than a fixed-window counter
under bursty traffic without needing locks for the common case (the
deque is appended/trimmed in a single critical section).

Advisory invariants are preserved on rejection: 429 responses elsewhere
still stamp ``advisory_status=ADVISORY_ONLY`` and friends.  The limiter
itself only returns ``True``/``False`` plus retry advice and never touches
broker state.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of a single ``RateLimiter.check`` call.

    ``allowed`` is the only field a caller usually needs.  The other
    fields are surfaced so middleware can emit Retry-After headers and
    diagnostic JSON without recomputing anything.
    """

    allowed: bool
    remaining: int
    limit: int
    window_seconds: int
    retry_after_seconds: int


class RateLimiter:
    """Thread-safe sliding-window limiter keyed by an arbitrary string.

    Designed for a single-process FastAPI server.  Memory cost is
    O(active_keys * max_requests) which is bounded by ``max_requests``
    being a small int and active_keys being one-per-IP-per-route-group.

    Usage::

        limiter = RateLimiter(max_requests=60, window_seconds=60)
        decision = limiter.check("203.0.113.7:read")
        if not decision.allowed:
            raise HTTPException(429, "rate limited")
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        *,
        clock=time.monotonic,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        self._max = int(max_requests)
        self._window = int(window_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, Deque[float]] = {}

    @property
    def max_requests(self) -> int:
        return self._max

    @property
    def window_seconds(self) -> int:
        return self._window

    def reset(self) -> None:
        """Drop all bucket state.  Tests use this between cases."""
        with self._lock:
            self._buckets.clear()

    def check(self, key: str) -> RateLimitDecision:
        """Record an attempted request and return whether it is allowed."""
        now = self._clock()
        cutoff = now - self._window
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = deque()
                self._buckets[key] = bucket
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                oldest = bucket[0]
                retry_after = max(1, int(self._window - (now - oldest) + 1))
                return RateLimitDecision(
                    allowed=False,
                    remaining=0,
                    limit=self._max,
                    window_seconds=self._window,
                    retry_after_seconds=retry_after,
                )
            bucket.append(now)
            return RateLimitDecision(
                allowed=True,
                remaining=self._max - len(bucket),
                limit=self._max,
                window_seconds=self._window,
                retry_after_seconds=0,
            )


__all__ = ["RateLimiter", "RateLimitDecision"]
