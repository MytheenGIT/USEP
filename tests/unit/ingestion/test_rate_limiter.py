from __future__ import annotations

from uuid import uuid4

import pytest
from tests.fakes.clock import FakeClock

from usep.ingestion.runtime.rate_limiter import RateLimiter, RateLimitKey

TENANT = uuid4()


def test_429_pauses_whole_key() -> None:
    """CC-03: a penalty on a key blocks every subsequent acquire on that same key."""
    clock = FakeClock()
    limiter = RateLimiter(clock, backfill_fraction=0.5)
    limiter.configure(TENANT, "jira", "acct", rate_per_second=100.0)
    key = RateLimitKey(TENANT, "jira", "acct", "live")

    assert limiter.wait_seconds(key) == 0.0
    limiter.penalize(key, duration_seconds=30.0)
    assert limiter.wait_seconds(key) == pytest.approx(30.0)
    clock.advance(10.0)
    assert limiter.wait_seconds(key) == pytest.approx(20.0)
    clock.advance(20.0)
    assert limiter.wait_seconds(key) == 0.0


def test_backfill_never_exceeds_fraction() -> None:
    """Backfill lane's configured rate is exactly `live_rate * backfill_fraction`,
    and the two lanes are independent buckets (LLD §4.3)."""
    clock = FakeClock()
    limiter = RateLimiter(clock, backfill_fraction=0.5)
    limiter.configure(TENANT, "jira", "acct", rate_per_second=10.0, capacity=10.0)

    live_key = RateLimitKey(TENANT, "jira", "acct", "live")
    backfill_key = RateLimitKey(TENANT, "jira", "acct", "backfill")

    # Drain the live bucket completely; it should not affect the backfill bucket's tokens.
    for _ in range(10):
        limiter._bucket(live_key).reserve(clock.now())  # type: ignore[attr-defined]
    assert limiter.wait_seconds(live_key) > 0.0
    assert limiter.wait_seconds(backfill_key) == 0.0  # untouched, still has its own tokens


def test_live_unaffected_by_saturated_backfill() -> None:
    """Draining the backfill bucket does not touch the live bucket's tokens."""
    clock = FakeClock()
    limiter = RateLimiter(clock, backfill_fraction=0.5)
    limiter.configure(TENANT, "confluence", "acct", rate_per_second=10.0, capacity=10.0)

    live_key = RateLimitKey(TENANT, "confluence", "acct", "live")
    backfill_key = RateLimitKey(TENANT, "confluence", "acct", "backfill")

    backfill_capacity = limiter._bucket(backfill_key).capacity  # type: ignore[attr-defined]
    for _ in range(int(backfill_capacity)):
        limiter._bucket(backfill_key).reserve(clock.now())  # type: ignore[attr-defined]

    assert limiter.wait_seconds(backfill_key) > 0.0
    assert limiter.wait_seconds(live_key) == 0.0


@pytest.mark.asyncio
async def test_acquire_consumes_a_token_and_reports_wait() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock, backfill_fraction=0.5)
    limiter.configure(TENANT, "git", "acct", rate_per_second=1000.0)
    key = RateLimitKey(TENANT, "git", "acct", "live")

    waited = await limiter.acquire(key)
    assert waited == 0.0


@pytest.mark.asyncio
async def test_concurrent_callers_on_an_empty_bucket_queue_up_instead_of_bursting() -> None:
    """Ten callers arriving together on a 100/s bucket must wait 10 ms, 20 ms ... 100 ms."""
    import asyncio

    clock = FakeClock()
    limiter = RateLimiter(clock, backfill_fraction=0.5)
    limiter.configure(TENANT, "jira", "acct", rate_per_second=100.0, capacity=1.0)
    key = RateLimitKey(TENANT, "jira", "acct", "live")
    await limiter.acquire(key)  # drain the single token

    waits = sorted(await asyncio.gather(*(limiter.acquire(key) for _ in range(10))))

    assert waits == pytest.approx([0.01 * n for n in range(1, 11)])
