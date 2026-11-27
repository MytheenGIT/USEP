from __future__ import annotations

import datetime as dt
import logging
from uuid import uuid4

import pytest
from tests.fakes.clock import FakeClock

from usep.core.errors import TransientError
from usep.ingestion.runtime.http import Classification
from usep.ingestion.runtime.observer import ListObserver
from usep.ingestion.runtime.rate_limiter import RateLimiter, RateLimitKey
from usep.ingestion.runtime.retry import CallResult, Outcome, RetryPolicy, SendOutcome, call_with_retry

TENANT = uuid4()
_ECHOED_SECRET = "glpat-abcdefghijklmnopqrstuvwxyz"  # SYNTHETIC


def _key() -> RateLimitKey:
    return RateLimitKey(TENANT, "jira", "acct", "live")


class _Scripted:
    """A `send` callable that returns a fixed sequence of `SendOutcome`s, then errors
    if called more times than scripted."""

    def __init__(self, outcomes: list[SendOutcome[str]]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    async def __call__(self) -> SendOutcome[str]:
        outcome = self._outcomes[self.calls]
        self.calls += 1
        return outcome


def _limiter(clock: FakeClock) -> RateLimiter:
    limiter = RateLimiter(clock, backfill_fraction=0.5)
    limiter.configure(TENANT, "jira", "acct", rate_per_second=1000.0)
    return limiter


@pytest.mark.asyncio
async def test_ok_on_first_attempt() -> None:
    clock = FakeClock()
    send = _Scripted([SendOutcome(Classification.OK, value="ok")])
    result = await call_with_retry(
        send,
        key=_key(),
        policy=RetryPolicy(),
        rate_limiter=_limiter(clock),
        clock=clock,
        observer=ListObserver(),
        endpoint="/issues",
        source_system="jira",
    )
    assert result == CallResult(Outcome.OK, value="ok", attempts=1)


@pytest.mark.asyncio
async def test_other_4xx_is_rejected_without_retry() -> None:
    clock = FakeClock()
    send = _Scripted([SendOutcome(Classification.REJECTED, reason="404")])
    result = await call_with_retry(
        send,
        key=_key(),
        policy=RetryPolicy(),
        rate_limiter=_limiter(clock),
        clock=clock,
        observer=ListObserver(),
        endpoint="/issues",
        source_system="jira",
    )
    assert result.outcome is Outcome.REJECTED
    assert result.attempts == 1
    assert send.calls == 1


@pytest.mark.asyncio
async def test_unexpected_exception_is_rejected_recording_type_only() -> None:
    clock = FakeClock()

    async def send() -> SendOutcome[str]:
        raise ValueError("boom with a secret glpat-abcdefghijklmnopqrstuvwxyz")  # SYNTHETIC

    result = await call_with_retry(
        send,
        key=_key(),
        policy=RetryPolicy(),
        rate_limiter=_limiter(clock),
        clock=clock,
        observer=ListObserver(),
        endpoint="/issues",
        source_system="jira",
    )
    assert result.outcome is Outcome.REJECTED
    assert result.reason == "ValueError"
    assert "glpat" not in result.reason


@pytest.mark.asyncio
async def test_transient_error_retries_then_dead_letters() -> None:
    clock = FakeClock()
    policy = RetryPolicy(max_attempts=3, base_delay_s=0.001, max_delay_s=0.01)

    async def always_transient() -> SendOutcome[str]:
        raise TransientError("connect timeout")

    observer = ListObserver()
    result = await call_with_retry(
        always_transient,
        key=_key(),
        policy=policy,
        rate_limiter=_limiter(clock),
        clock=clock,
        observer=observer,
        endpoint="/issues",
        source_system="jira",
    )
    assert result.outcome is Outcome.DEAD_LETTER
    assert result.attempts == 3


@pytest.mark.asyncio
async def test_retryable_5xx_eventually_succeeds() -> None:
    clock = FakeClock()
    policy = RetryPolicy(max_attempts=5, base_delay_s=0.001, max_delay_s=0.01)
    send = _Scripted(
        [
            SendOutcome(Classification.RETRYABLE, reason="503"),
            SendOutcome(Classification.RETRYABLE, reason="503"),
            SendOutcome(Classification.OK, value="recovered"),
        ]
    )
    result = await call_with_retry(
        send,
        key=_key(),
        policy=policy,
        rate_limiter=_limiter(clock),
        clock=clock,
        observer=ListObserver(),
        endpoint="/issues",
        source_system="jira",
    )
    assert result == CallResult(Outcome.OK, value="recovered", attempts=3)


@pytest.mark.asyncio
async def test_retry_after_within_cap_honoured() -> None:
    """CC-03: a 429 with Retry-After <= 600s waits exactly that long, then retries."""
    clock = FakeClock()
    policy = RetryPolicy(max_delay_s=600.0)
    send = _Scripted(
        [
            SendOutcome(Classification.RETRYABLE, is_429=True, retry_after_s=5.0, reason="429"),
            SendOutcome(Classification.OK, value="ok"),
        ]
    )
    observer = ListObserver()
    result = await call_with_retry(
        send,
        key=_key(),
        policy=policy,
        rate_limiter=_limiter(clock),
        clock=clock,
        observer=observer,
        endpoint="/issues",
        source_system="jira",
    )
    assert result == CallResult(Outcome.OK, value="ok", attempts=2)
    retry_events = [e for e in observer.events if type(e).__name__ == "RetryEvent"]
    assert retry_events[0].delay_s == 5.0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_retry_after_over_cap_deferred() -> None:
    """CC-03, D7: Retry-After > 600s returns DEFERRED with retry_at, not a retry loop."""
    clock = FakeClock()
    policy = RetryPolicy(max_delay_s=600.0, defer_max_s=86400.0)
    send = _Scripted([SendOutcome(Classification.RETRYABLE, is_429=True, retry_after_s=900.0, reason="429")])
    result = await call_with_retry(
        send,
        key=_key(),
        policy=policy,
        rate_limiter=_limiter(clock),
        clock=clock,
        observer=ListObserver(),
        endpoint="/issues",
        source_system="jira",
    )
    assert result.outcome is Outcome.DEFERRED
    assert result.reason == "retry_after_over_cap"
    assert result.retry_at is not None
    assert send.calls == 1  # never retried in-process; caller schedules the retry


@pytest.mark.asyncio
async def test_retry_after_exceeding_defer_max_is_flagged_distinctly() -> None:
    """D7: Retry-After > 24h is still DEFERRED, but flagged so the caller can pause the scope."""
    clock = FakeClock()
    policy = RetryPolicy(max_delay_s=600.0, defer_max_s=86400.0)
    send = _Scripted(
        [SendOutcome(Classification.RETRYABLE, is_429=True, retry_after_s=90_000.0, reason="429")]
    )
    result = await call_with_retry(
        send,
        key=_key(),
        policy=policy,
        rate_limiter=_limiter(clock),
        clock=clock,
        observer=ListObserver(),
        endpoint="/issues",
        source_system="jira",
    )
    assert result.outcome is Outcome.DEFERRED
    assert result.reason == "retry_after_exceeds_defer_max"


@pytest.mark.asyncio
async def test_429_penalizes_the_rate_limit_key() -> None:
    clock = FakeClock()
    limiter = _limiter(clock)
    key = _key()
    send = _Scripted(
        [
            SendOutcome(Classification.RETRYABLE, is_429=True, retry_after_s=None, reason="429"),
            SendOutcome(Classification.OK, value="ok"),
        ]
    )
    policy = RetryPolicy(base_delay_s=0.001, max_delay_s=0.01)
    await call_with_retry(
        send,
        key=key,
        policy=policy,
        rate_limiter=limiter,
        clock=clock,
        observer=ListObserver(),
        endpoint="/issues",
        source_system="jira",
    )
    # The 429 should have set a penalty that was still (partially) in effect right
    # after the call returned (penalty duration = base_delay_s, which also drove the
    # retry's own backoff, so by completion the penalty may have fully elapsed via the
    # sleep; assert it was set at least once by checking the bucket directly).
    assert limiter._bucket(key).penalized_until is not None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_retry_after_on_every_attempt_dead_letters_at_max_attempts() -> None:
    clock = FakeClock()
    policy = RetryPolicy(max_attempts=3, max_delay_s=600.0)
    send = _Scripted(
        [SendOutcome(Classification.RETRYABLE, is_429=True, retry_after_s=0.001, reason="429")] * 10
    )
    result = await call_with_retry(
        send,
        key=_key(),
        policy=policy,
        rate_limiter=_limiter(clock),
        clock=clock,
        observer=ListObserver(),
        endpoint="/issues",
        source_system="jira",
    )
    assert result.outcome is Outcome.DEAD_LETTER
    assert result.attempts == 3
    assert send.calls == 3


@pytest.mark.asyncio
async def test_absurd_retry_after_is_deferred_at_the_defer_cap_instead_of_overflowing() -> None:
    clock = FakeClock()
    policy = RetryPolicy(max_delay_s=600.0, defer_max_s=86400.0)
    send = _Scripted([SendOutcome(Classification.RETRYABLE, is_429=True, retry_after_s=1e15, reason="429")])
    result = await call_with_retry(
        send,
        key=_key(),
        policy=policy,
        rate_limiter=_limiter(clock),
        clock=clock,
        observer=ListObserver(),
        endpoint="/issues",
        source_system="jira",
    )
    assert result.outcome is Outcome.DEFERRED
    assert result.reason == "retry_after_exceeds_defer_max"
    assert result.retry_at == clock.now() + dt.timedelta(seconds=86400.0)


@pytest.mark.asyncio
async def test_unexpected_exception_is_logged_with_type_and_frames_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = FakeClock()

    async def send() -> SendOutcome[str]:
        raise ValueError(f"boom with {_ECHOED_SECRET}")

    with caplog.at_level(logging.ERROR, logger="usep.ingestion.runtime.retry"):
        await call_with_retry(
            send,
            key=_key(),
            policy=RetryPolicy(),
            rate_limiter=_limiter(clock),
            clock=clock,
            observer=ListObserver(),
            endpoint="/issues",
            source_system="jira",
        )
    record = next(r for r in caplog.records if r.getMessage() == "unexpected exception from send")
    assert record.exception_type == "ValueError"  # type: ignore[attr-defined]
    assert record.endpoint == "/issues"  # type: ignore[attr-defined]
    assert "glpat" not in caplog.text


@pytest.mark.asyncio
async def test_dead_letter_is_logged_as_an_error_with_reason_and_attempts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = FakeClock()

    async def always_transient() -> SendOutcome[str]:
        raise TransientError(f"connect timeout {_ECHOED_SECRET}")

    with caplog.at_level(logging.INFO, logger="usep.ingestion.runtime.retry"):
        await call_with_retry(
            always_transient,
            key=_key(),
            policy=RetryPolicy(max_attempts=2, base_delay_s=0.001, max_delay_s=0.01),
            rate_limiter=_limiter(clock),
            clock=clock,
            observer=ListObserver(),
            endpoint="/issues",
            source_system="jira",
        )

    retrying = next(r for r in caplog.records if r.getMessage() == "call retrying")
    dead = next(r for r in caplog.records if r.getMessage() == "call dead-lettered")
    assert (retrying.levelno, dead.levelno) == (logging.INFO, logging.ERROR)
    assert (dead.reason, dead.attempts, dead.endpoint) == ("TransientError", 2, "/issues")  # type: ignore[attr-defined]
    assert "glpat" not in caplog.text


@pytest.mark.asyncio
async def test_deferral_is_logged_as_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    clock = FakeClock()
    send = _Scripted([SendOutcome(Classification.RETRYABLE, is_429=True, retry_after_s=900.0, reason="429")])

    with caplog.at_level(logging.INFO, logger="usep.ingestion.runtime.retry"):
        await call_with_retry(
            send,
            key=_key(),
            policy=RetryPolicy(),
            rate_limiter=_limiter(clock),
            clock=clock,
            observer=ListObserver(),
            endpoint="/issues",
            source_system="jira",
        )

    record = next(r for r in caplog.records if r.getMessage() == "call deferred")
    assert record.levelno == logging.WARNING
    assert record.reason == "retry_after_over_cap"  # type: ignore[attr-defined]
