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
from usep.core.defaults import (
    DEFAULT_BASE_DELAY_S,
    DEFAULT_DEFER_MAX_S,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_DELAY_S,
    MILLISECONDS_PER_SECOND,
)
from usep.core.errors import TransientError, frames_only
from usep.ingestion.domain.outcome import Outcome
from usep.ingestion.runtime.backoff import compute_delay
from usep.ingestion.runtime.http import Classification
from usep.ingestion.runtime.observer import Observer
from usep.ingestion.runtime.rate_limiter import RateLimiter, RateLimitKey

logger = logging.getLogger(__name__)


class RetryReason(StrEnum):
    """Why a call is being retried, or why it stopped."""

    RETRYABLE = "retryable"
    RETRY_AFTER = "retry_after"
    RETRY_AFTER_OVER_CAP = "retry_after_over_cap"
    RETRY_AFTER_EXCEEDS_DEFER_MAX = "retry_after_exceeds_defer_max"


def _log_call(
    level: int, message: str, *, source_system: str, endpoint: str, reason: str, attempts: int
) -> None:
    """Log how a call is being handled: IDs, reason and attempt count only, never content."""
    logger.log(
        level,
        message,
        extra={"source_system": source_system, "endpoint": endpoint, "reason": reason, "attempts": attempts},
    )


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
    """Limits for retrying a call: attempts, back-off bounds and the deferral cap."""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_delay_s: float = DEFAULT_BASE_DELAY_S
    max_delay_s: float = DEFAULT_MAX_DELAY_S
    defer_max_s: float = DEFAULT_DEFER_MAX_S


@dataclass(frozen=True, slots=True)
class CallResult[T]:
    """How a call ended, with its value, retry time, attempt count and reason."""

    outcome: Outcome
    value: T | None = None
    retry_at: datetime | None = None
    attempts: int = 0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class _Call:
    """What stays the same across the attempts of one call, and how each outcome is reported."""

    key: RateLimitKey
    policy: RetryPolicy
    rate_limiter: RateLimiter
    clock: Clock
    observer: Observer
    endpoint: str
    source_system: str

    def observe_attempt(
        self, *, status: str | None, start: datetime, attempt: int, error_type: str | None
    ) -> None:
        """Tell the observer about one finished attempt."""
        latency_ms = (self.clock.now() - start).total_seconds() * MILLISECONDS_PER_SECOND
        self.observer.attempt(
            source_system=self.source_system,
            endpoint=self.endpoint,
            status=status,
            latency_ms=latency_ms,
            retry_count=attempt - 1,
            error_type=error_type,
        )

    def reject_unexpected[T](self, exc: Exception, start: datetime, attempt: int) -> CallResult[T]:
        """Log an unexpected exception from `send` and reject the call; it is not retried."""
        logger.error(
            "unexpected exception from send",
            extra={
                "source_system": self.source_system,
                "endpoint": self.endpoint,
                "exception_type": type(exc).__name__,
                "frames": frames_only(exc),
            },
        )
        self.observe_attempt(status=None, start=start, attempt=attempt, error_type=type(exc).__name__)
        return CallResult(Outcome.REJECTED, attempts=attempt, reason=type(exc).__name__)

    def dead_letter[T](self, reason: str, attempt: int) -> CallResult[T]:
        """Report that the retries ran out."""
        self.observer.dead_letter(source_system=self.source_system, endpoint=self.endpoint, reason=reason)
        _log_call(
            logging.ERROR,
            "call dead-lettered",
            source_system=self.source_system,
            endpoint=self.endpoint,
            reason=reason,
            attempts=attempt,
        )
        return CallResult(Outcome.DEAD_LETTER, attempts=attempt, reason=reason)

    def defer[T](self, retry_after_s: float, attempt: int) -> CallResult[T]:
        """Report a deferral to the time the source asked for, capped at `defer_max_s`.

        D7: over the retry cap a call is deferred instead of dead-lettered. Over `defer_max_s`
        (24h) the caller must pause the scope and raise the alert; this module only flags that
        case in `reason`. The capped time also keeps an absurd header from overflowing the date.
        """
        retry_at = self.clock.now() + timedelta(seconds=min(retry_after_s, self.policy.defer_max_s))
        self.observer.deferred(source_system=self.source_system, endpoint=self.endpoint, retry_at=retry_at)
        reason: str = (
            RetryReason.RETRY_AFTER_EXCEEDS_DEFER_MAX
            if retry_after_s > self.policy.defer_max_s
            else RetryReason.RETRY_AFTER_OVER_CAP
        )
        _log_call(
            logging.WARNING,
            "call deferred",
            source_system=self.source_system,
            endpoint=self.endpoint,
            reason=reason,
            attempts=attempt,
        )
        return CallResult(Outcome.DEFERRED, attempts=attempt, retry_at=retry_at, reason=reason)

    def announce_retry(self, reason: str, delay_s: float, attempt: int) -> float:
        """Report a scheduled retry and return the delay to wait."""
        self.observer.retry(
            source_system=self.source_system, endpoint=self.endpoint, reason=reason, delay_s=delay_s
        )
        _log_call(
            logging.INFO,
            "call retrying",
            source_system=self.source_system,
            endpoint=self.endpoint,
            reason=reason,
            attempts=attempt,
        )
        return delay_s


def _after_transient[T](call: _Call, exc: TransientError, attempt: int) -> CallResult[T] | float:
    """Decide what follows a transient failure: a dead letter, or the delay before the retry."""
    reason = type(exc).__name__
    if attempt >= call.policy.max_attempts:
        return call.dead_letter(reason, attempt)
    delay = compute_delay(attempt, call.policy.base_delay_s, call.policy.max_delay_s)
    return call.announce_retry(reason, delay, attempt)


def _after_response[T](call: _Call, outcome: SendOutcome[T], attempt: int) -> CallResult[T] | float:
    """Decide what follows a response: a final result, or the delay before the retry."""
    if outcome.classification is Classification.OK:
        return CallResult(Outcome.OK, value=outcome.value, attempts=attempt)
    if outcome.classification is Classification.REJECTED:
        return CallResult(Outcome.REJECTED, attempts=attempt, reason=outcome.reason)

    # RETRYABLE: 429 or 5xx. Penalize the whole key on any 429 (section 5.7).
    retry_after = outcome.retry_after_s if outcome.is_429 else None
    if outcome.is_429:
        penalty = min(outcome.retry_after_s or call.policy.base_delay_s, call.policy.max_delay_s)
        call.rate_limiter.penalize(call.key, duration_seconds=penalty)
    if retry_after is not None and retry_after > call.policy.max_delay_s:
        return call.defer(retry_after, attempt)

    reason = outcome.reason or RetryReason.RETRYABLE
    if attempt >= call.policy.max_attempts:
        return call.dead_letter(reason, attempt)
    if retry_after is not None:
        return call.announce_retry(RetryReason.RETRY_AFTER, retry_after, attempt)
    delay = compute_delay(attempt, call.policy.base_delay_s, call.policy.max_delay_s)
    return call.announce_retry(reason, delay, attempt)


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
    call = _Call(key, policy, rate_limiter, clock, observer, endpoint, source_system)
    attempt = 0
    while True:
        attempt += 1
        wait = await rate_limiter.acquire(key)
        if wait > 0:
            observer.rate_wait(source_system=source_system, lane=key.lane, seconds=wait)

        start = clock.now()
        step: CallResult[T] | float
        try:
            outcome = await send()
        except TransientError as exc:
            call.observe_attempt(status=None, start=start, attempt=attempt, error_type=type(exc).__name__)
            step = _after_transient(call, exc, attempt)
        except Exception as exc:  # noqa: BLE001 - unexpected exceptions are rejected, not retried
            return call.reject_unexpected(exc, start, attempt)
        else:
            call.observe_attempt(
                status=outcome.classification.value, start=start, attempt=attempt, error_type=None
            )
            step = _after_response(call, outcome, attempt)

        if isinstance(step, CallResult):
            return step
        await asyncio.sleep(step)
