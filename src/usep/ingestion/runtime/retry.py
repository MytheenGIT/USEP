"""`call_with_retry`: acquire a rate-limit token, send, classify, retry (section 5.7).

`send` is supplied by the caller (ultimately a connector adapter in a later phase;
here, only test fakes) as a zero-argument async callable returning a `SendOutcome`.
This module never sees a real HTTP response or vendor exception type — only the
vendor-neutral `Classification` from `usep.ingestion.runtime.http`, or a raised
`TransientError` / arbitrary exception — so it stays free of any vendor import.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from usep.core.clock import Clock
from usep.core.errors import TransientError, frames_only
from usep.ingestion.runtime.backoff import compute_delay
from usep.ingestion.runtime.http import Classification
from usep.ingestion.runtime.observer import Observer
from usep.ingestion.runtime.rate_limiter import RateLimiter, RateLimitKey

logger = logging.getLogger(__name__)


class Outcome(StrEnum):
    OK = "OK"
    REJECTED = "REJECTED"
    DEAD_LETTER = "DEAD_LETTER"
    DEFERRED = "DEFERRED"


@dataclass(frozen=True, slots=True)
class SendOutcome[T]:
    """What the caller's `send()` returns: its classification of one HTTP attempt."""

    classification: Classification
    value: T | None = None
    is_429: bool = False
    retry_after_s: float | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_s: float = 2.0
    max_delay_s: float = 600.0
    defer_max_s: float = 86400.0


@dataclass(frozen=True, slots=True)
class CallResult[T]:
    outcome: Outcome
    value: T | None = None
    retry_at: datetime | None = None
    attempts: int = 0
    reason: str = ""


async def call_with_retry[T](
    send: Callable[[], Awaitable[SendOutcome[T]]],
    *,
    key: RateLimitKey,
    policy: RetryPolicy,
    rate_limiter: RateLimiter,
    clock: Clock,
    observer: Observer,
    endpoint: str,
    source_system: str,
) -> CallResult[T]:
    """Send one request, retrying transient failures, and report how it ended.

    Args:
        send: Makes one attempt and classifies the response. May raise `TransientError`.
        key: Rate-limit budget the attempts draw from.
        policy: Attempt cap, back-off bounds and deferral limits.
        rate_limiter: Source of tokens and of the pause applied after a 429.
        clock: Time source for latency and deferral timestamps.
        observer: Receives one event per attempt, wait, retry, deferral and dead letter.
        endpoint: Endpoint label for observer events.
        source_system: Source label for observer events.

    Returns:
        `OK` with the value; `REJECTED` for a non-retryable response or an unexpected
        exception; `DEAD_LETTER` after `policy.max_attempts` attempts, whether the server
        sent `Retry-After` or not; `DEFERRED` when `Retry-After` exceeds `policy.max_delay_s`.
    """
    attempt = 0
    while True:
        attempt += 1
        wait = await rate_limiter.acquire(key)
        if wait > 0:
            observer.rate_wait(source_system=source_system, lane=key.lane, seconds=wait)

        start = clock.now()
        try:
            outcome = await send()
        except TransientError as exc:
            latency_ms = (clock.now() - start).total_seconds() * 1000
            observer.attempt(
                source_system=source_system,
                endpoint=endpoint,
                status=None,
                latency_ms=latency_ms,
                retry_count=attempt - 1,
                error_type=type(exc).__name__,
            )
            if attempt >= policy.max_attempts:
                observer.dead_letter(
                    source_system=source_system, endpoint=endpoint, reason=type(exc).__name__
                )
                return CallResult(Outcome.DEAD_LETTER, attempts=attempt, reason=type(exc).__name__)
            delay = compute_delay(attempt, policy.base_delay_s, policy.max_delay_s)
            observer.retry(
                source_system=source_system, endpoint=endpoint, reason=type(exc).__name__, delay_s=delay
            )
            await asyncio.sleep(delay)
            continue
        except Exception as exc:  # noqa: BLE001 - unexpected exceptions are rejected, not retried
            logger.error(
                "unexpected exception from send",
                extra={
                    "source_system": source_system,
                    "endpoint": endpoint,
                    "exception_type": type(exc).__name__,
                    "frames": frames_only(exc),
                },
            )
            latency_ms = (clock.now() - start).total_seconds() * 1000
            observer.attempt(
                source_system=source_system,
                endpoint=endpoint,
                status=None,
                latency_ms=latency_ms,
                retry_count=attempt - 1,
                error_type=type(exc).__name__,
            )
            return CallResult(Outcome.REJECTED, attempts=attempt, reason=type(exc).__name__)

        latency_ms = (clock.now() - start).total_seconds() * 1000
        observer.attempt(
            source_system=source_system,
            endpoint=endpoint,
            status=outcome.classification.value,
            latency_ms=latency_ms,
            retry_count=attempt - 1,
            error_type=None,
        )

        if outcome.classification is Classification.OK:
            return CallResult(Outcome.OK, value=outcome.value, attempts=attempt)

        if outcome.classification is Classification.REJECTED:
            return CallResult(Outcome.REJECTED, attempts=attempt, reason=outcome.reason)

        # RETRYABLE: 429 or 5xx. Penalize the whole key on any 429 (section 5.7).
        if outcome.is_429:
            penalty = min(outcome.retry_after_s or policy.base_delay_s, policy.max_delay_s)
            rate_limiter.penalize(key, duration_seconds=penalty)

        if (
            outcome.is_429
            and outcome.retry_after_s is not None
            and outcome.retry_after_s > policy.max_delay_s
        ):
            # D7: over the 600s cap, defer rather than dead-letter; over defer_max_s
            # (24h), the caller (cursor/reconcile orchestration, PR 5) is responsible
            # for transitioning the scope to PAUSED and emitting the alert event —
            # this module only flags that case via `reason`. retry_at is capped at
            # defer_max_s so an absurd header cannot overflow the datetime.
            retry_after = outcome.retry_after_s
            retry_at = clock.now() + timedelta(seconds=min(retry_after, policy.defer_max_s))
            observer.deferred(source_system=source_system, endpoint=endpoint, retry_at=retry_at)
            reason = (
                "retry_after_exceeds_defer_max"
                if retry_after > policy.defer_max_s
                else "retry_after_over_cap"
            )
            return CallResult(Outcome.DEFERRED, attempts=attempt, retry_at=retry_at, reason=reason)

        reason = outcome.reason or "retryable"
        if attempt >= policy.max_attempts:
            observer.dead_letter(source_system=source_system, endpoint=endpoint, reason=reason)
            return CallResult(Outcome.DEAD_LETTER, attempts=attempt, reason=reason)

        if outcome.is_429 and outcome.retry_after_s is not None:
            reason, delay = "retry_after", outcome.retry_after_s
        else:
            delay = compute_delay(attempt, policy.base_delay_s, policy.max_delay_s)
        observer.retry(source_system=source_system, endpoint=endpoint, reason=reason, delay_s=delay)
        await asyncio.sleep(delay)
