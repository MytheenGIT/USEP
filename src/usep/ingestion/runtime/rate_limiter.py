"""Token-bucket rate limiting, keyed (tenant, source_system, account, lane) (section 5.7).

The live and backfill lanes for the same (tenant, source_system, account) are always
two independent bucket instances — the backfill lane's rate is a configured fraction
of the live lane's, but the two buckets never share tokens, so a saturated backfill
lane can never starve the live lane (LLD §4.3).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from usep.core.clock import Clock
from usep.ingestion.domain.cursor import Lane

DEFAULT_RATE_PER_SECOND = 1.0


@dataclass(frozen=True, slots=True)
class RateLimitKey:
    """Identifies one rate-limit budget: tenant, source system, account and lane."""

    tenant_id: UUID
    source_system: str
    account: str
    lane: Lane


@dataclass(slots=True)
class _Bucket:
    rate_per_second: float
    capacity: float
    tokens: float
    updated_at: datetime
    penalized_until: datetime | None = None

    def _refill(self, now: datetime) -> None:
        elapsed = max((now - self.updated_at).total_seconds(), 0.0)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_second)
        self.updated_at = now

    def wait_seconds(self, now: datetime) -> float:
        """Return how long a caller must wait for a token and any penalty."""
        self._refill(now)
        candidates = [0.0]
        if self.tokens < 1:
            candidates.append(
                (1 - self.tokens) / self.rate_per_second if self.rate_per_second > 0 else float("inf")
            )
        if self.penalized_until is not None:
            candidates.append(max((self.penalized_until - now).total_seconds(), 0.0))
        return max(candidates)

    def reserve(self, now: datetime) -> float:
        """Take one token now and return how long the caller must wait before using it.

        The token count may go negative: each concurrent caller reserves its own slot, so
        N callers are spread over N token intervals instead of all waking at once.
        """
        wait = self.wait_seconds(now)
        self.tokens -= 1
        return wait


class RateLimiter:
    """Owns one `_Bucket` per `RateLimitKey`."""

    def __init__(self, clock: Clock, *, backfill_fraction: float) -> None:
        """Build the limiter.

        Args:
            clock: Time source.
            backfill_fraction: The backfill lane's rate as a fraction of the live lane's.
        """
        self._clock = clock
        self._backfill_fraction = backfill_fraction
        self._buckets: dict[RateLimitKey, _Bucket] = {}

    def configure(
        self,
        tenant_id: UUID,
        source_system: str,
        account: str,
        *,
        rate_per_second: float,
        capacity: float | None = None,
    ) -> None:
        """Set the live lane's rate; the backfill lane's rate is derived from it.

        The backfill lane's rate is `rate_per_second * backfill_fraction` (default fraction 0.5).

        Raises:
            ValueError: If `rate_per_second` is not positive (a zero rate would block forever).
        """
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        now = self._clock.now()
        live_capacity = capacity if capacity is not None else max(rate_per_second, 1.0)
        self._buckets[RateLimitKey(tenant_id, source_system, account, Lane.LIVE)] = _Bucket(
            rate_per_second, live_capacity, live_capacity, now
        )
        backfill_rate = rate_per_second * self._backfill_fraction
        backfill_capacity = max(backfill_rate, 1.0)
        self._buckets[RateLimitKey(tenant_id, source_system, account, Lane.BACKFILL)] = _Bucket(
            backfill_rate, backfill_capacity, backfill_capacity, now
        )

    def _bucket(self, key: RateLimitKey) -> _Bucket:
        if key not in self._buckets:
            # Conservative default for an unconfigured key, so a caller that forgets to call
            # configure() still gets rate-limited rather than unlimited.
            self.configure(
                key.tenant_id, key.source_system, key.account, rate_per_second=DEFAULT_RATE_PER_SECOND
            )
        return self._buckets[key]

    def wait_seconds(self, key: RateLimitKey) -> float:
        """Return how long a caller must wait for a token and any penalty."""
        return self._bucket(key).wait_seconds(self._clock.now())

    async def acquire(self, key: RateLimitKey) -> float:
        """Reserve a token, then wait for it and for any active penalty to expire.

        Returns the number of seconds slept (0 if none).

        The reservation happens before the first `await`, so concurrent callers on one key
        cannot all see the same free token.
        """
        wait = self._bucket(key).reserve(self._clock.now())
        if wait > 0:
            await asyncio.sleep(wait)
        return wait

    def penalize(self, key: RateLimitKey, duration_seconds: float) -> None:
        """Pause every caller on this key for `duration_seconds`.

        Section 5.7: a penalty pauses every caller on a key after a 429.
        """
        bucket = self._bucket(key)
        until = self._clock.now() + timedelta(seconds=duration_seconds)
        # Keep the longer pause: a later 429 with a short Retry-After must not cut a long one short.
        bucket.penalized_until = (
            until if bucket.penalized_until is None else max(until, bucket.penalized_until)
        )
