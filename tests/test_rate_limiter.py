"""Pure-logic tests for ``scripts.rate_limiter``.

These tests do not need FastAPI; they use a controllable monotonic clock so
sliding-window behaviour is deterministic regardless of CPU speed.

Safety invariants the limiter never weakens: it never returns ``True`` on
overflow, never executes broker calls, never bypasses the advisory lock.
The middleware that wraps this limiter stamps advisory_status etc. on the
429 response separately (covered in test_security_middleware.py).
"""
from __future__ import annotations

import pytest

from scripts.rate_limiter import RateLimitDecision, RateLimiter


class _FakeClock:
    """Monotonic clock substitute so tests don't sleep."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = float(start)

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += float(seconds)


def test_constructor_rejects_zero_limit():
    with pytest.raises(ValueError):
        RateLimiter(max_requests=0, window_seconds=10)


def test_constructor_rejects_zero_window():
    with pytest.raises(ValueError):
        RateLimiter(max_requests=5, window_seconds=0)


def test_allows_up_to_limit_then_rejects():
    clock = _FakeClock()
    limiter = RateLimiter(max_requests=3, window_seconds=60, clock=clock)
    decisions = [limiter.check("alice") for _ in range(3)]
    for d in decisions:
        assert d.allowed is True
        assert isinstance(d, RateLimitDecision)
    # 4th request inside the window is rejected
    blocked = limiter.check("alice")
    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.retry_after_seconds >= 1
    assert blocked.limit == 3
    assert blocked.window_seconds == 60


def test_separate_keys_have_separate_buckets():
    clock = _FakeClock()
    limiter = RateLimiter(max_requests=2, window_seconds=60, clock=clock)
    assert limiter.check("alice").allowed is True
    assert limiter.check("alice").allowed is True
    # alice is full
    assert limiter.check("alice").allowed is False
    # bob is independent
    assert limiter.check("bob").allowed is True
    assert limiter.check("bob").allowed is True
    assert limiter.check("bob").allowed is False


def test_window_slides_so_old_requests_age_out():
    clock = _FakeClock()
    limiter = RateLimiter(max_requests=2, window_seconds=10, clock=clock)
    assert limiter.check("k").allowed is True
    assert limiter.check("k").allowed is True
    assert limiter.check("k").allowed is False
    # Advance past window
    clock.advance(11)
    fresh = limiter.check("k")
    assert fresh.allowed is True
    assert fresh.remaining == 1


def test_retry_after_is_positive_and_bounded():
    clock = _FakeClock()
    limiter = RateLimiter(max_requests=1, window_seconds=30, clock=clock)
    assert limiter.check("k").allowed is True
    blocked = limiter.check("k")
    assert blocked.allowed is False
    assert 1 <= blocked.retry_after_seconds <= 31


def test_reset_clears_state():
    clock = _FakeClock()
    limiter = RateLimiter(max_requests=1, window_seconds=60, clock=clock)
    assert limiter.check("k").allowed is True
    assert limiter.check("k").allowed is False
    limiter.reset()
    assert limiter.check("k").allowed is True


def test_remaining_decrements_per_request():
    clock = _FakeClock()
    limiter = RateLimiter(max_requests=4, window_seconds=60, clock=clock)
    assert limiter.check("k").remaining == 3
    assert limiter.check("k").remaining == 2
    assert limiter.check("k").remaining == 1
    assert limiter.check("k").remaining == 0
    blocked = limiter.check("k")
    assert blocked.allowed is False
    assert blocked.remaining == 0
