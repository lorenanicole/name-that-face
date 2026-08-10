"""
tests/unit/test_token_bucket.py

Unit tests for TokenBucketRateLimiter — pure logic, no I/O, no network.
Clock is injected so tests never sleep.
"""

import pytest

from rate_limiter import TokenBucketRateLimiter


@pytest.fixture
def clock():
    class FakeClock:
        def __init__(self):
            self.t = 0.0

        def __call__(self):
            return self.t

        def advance(self, dt: float):
            self.t += dt

    return FakeClock()


# ---------------------------------------------------------------------------
# Basic allow / deny
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_allows_up_to_capacity_then_blocks(clock):
    rl = TokenBucketRateLimiter(capacity=3, refill_rate=1, clock=clock)
    assert rl.allow("user") is True
    assert rl.allow("user") is True
    assert rl.allow("user") is True
    assert rl.allow("user") is False  # bucket empty


@pytest.mark.unit
def test_cost_greater_than_one(clock):
    rl = TokenBucketRateLimiter(capacity=5, refill_rate=1, clock=clock)
    assert rl.allow("user", cost=5) is True
    assert rl.allow("user", cost=1) is False
    assert rl.allow("user", cost=3) is False  # not enough for a burst


@pytest.mark.unit
def test_keys_are_independent(clock):
    rl = TokenBucketRateLimiter(capacity=1, refill_rate=1, clock=clock)
    assert rl.allow("alice") is True
    assert rl.allow("alice") is False
    assert rl.allow("bob") is True  # bob has his own bucket


# ---------------------------------------------------------------------------
# Refill behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_refills_over_time(clock):
    rl = TokenBucketRateLimiter(capacity=2, refill_rate=1, clock=clock)
    assert rl.allow("user") is True
    assert rl.allow("user") is True
    assert rl.allow("user") is False
    clock.advance(1.0)  # 1 token refilled
    assert rl.allow("user") is True
    assert rl.allow("user") is False


@pytest.mark.unit
def test_refill_capped_at_capacity(clock):
    rl = TokenBucketRateLimiter(capacity=2, refill_rate=1, clock=clock)
    clock.advance(100.0)  # would refill 100, but cap is 2
    assert rl.allow("user") is True
    assert rl.allow("user") is True
    assert rl.allow("user") is False


@pytest.mark.unit
def test_partial_refill_not_enough_for_request(clock):
    # Drain the bucket at t=0
    rl = TokenBucketRateLimiter(capacity=5, refill_rate=1, clock=clock)
    for _ in range(5):
        rl.allow("user")  # bucket empty; last_timestamp = 0.0
    # Sub-second advance: floor(0.9 * 1) = 0 new slots → still blocked
    clock.advance(0.9)
    assert rl.allow("user") is False  # denied; last_timestamp = 0.9
    # Advance a clean 1.0s from t=0 (drain point): jump straight to t=2.0
    # so elapsed from last_timestamp(0.9) = 1.1 → floor(1.1) = 1 slot
    clock.advance(1.1)
    assert rl.allow("user") is True


# ---------------------------------------------------------------------------
# Daily budget
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_daily_budget_exhausted_blocks_all_operations(clock):
    rl = TokenBucketRateLimiter(capacity=10, refill_rate=10, clock=clock)
    # budget = 3; each allow costs 1 slot
    assert rl.allow("user", operation="read", cost=1, daily_token_budget=3, rpm=10) is True
    assert rl.allow("user", operation="write", cost=1, daily_token_budget=3, rpm=10) is True
    assert rl.allow("user", operation="read", cost=1, daily_token_budget=3, rpm=10) is True
    # budget now 0 — both ops blocked regardless of bucket fill
    assert rl.allow("user", operation="read", cost=1, daily_token_budget=3, rpm=10) is False
    assert rl.allow("user", operation="write", cost=1, daily_token_budget=3, rpm=10) is False


# ---------------------------------------------------------------------------
# RPM window
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rpm_limit_enforced(clock):
    rl = TokenBucketRateLimiter(capacity=10, refill_rate=10, clock=clock)
    # rpm=2: only 2 requests allowed per 60-second window
    assert rl.allow("user", cost=1, daily_token_budget=1000, rpm=2) is True
    assert rl.allow("user", cost=1, daily_token_budget=1000, rpm=2) is True
    assert rl.allow("user", cost=1, daily_token_budget=1000, rpm=2) is False


@pytest.mark.unit
def test_rpm_window_resets_after_60s(clock):
    rl = TokenBucketRateLimiter(capacity=10, refill_rate=10, clock=clock)
    assert rl.allow("user", cost=1, daily_token_budget=1000, rpm=1) is True
    assert rl.allow("user", cost=1, daily_token_budget=1000, rpm=1) is False
    clock.advance(60.0)  # window rolls over
    assert rl.allow("user", cost=1, daily_token_budget=1000, rpm=1) is True


# ---------------------------------------------------------------------------
# operation_info snapshot
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_operation_info_returns_none_for_unseen_key(clock):
    rl = TokenBucketRateLimiter(capacity=5, refill_rate=1, clock=clock)
    assert rl.operation_info("ghost") is None


@pytest.mark.unit
def test_operation_info_reflects_consumption(clock):
    rl = TokenBucketRateLimiter(capacity=5, refill_rate=1, clock=clock)
    rl.allow("user", cost=2, daily_token_budget=100, rpm=10)
    info = rl.operation_info("user")
    assert info is not None
    assert info["tokens"] == 3.0
    assert info["remaining_daily_budget"] == 98.0
    assert info["remaining_rpm"] == 9.0
