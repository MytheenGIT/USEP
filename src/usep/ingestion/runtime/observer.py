"""The observer port: one event per attempt, wait, retry, deferral and dead letter.

Defined by sections 5.7 and 8.

`NoOpObserver` is the production default until a real metrics/tracing observer is wired in a later
phase; `ListObserver` lets tests assert on exactly what happened without needing a real collector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AttemptEvent:
    """One call attempt: the result, how long it took, and how many retries came before it."""

    source_system: str
    endpoint: str
    status: str | None
    latency_ms: float
    retry_count: int
    error_type: str | None


@dataclass(frozen=True, slots=True)
class RateWaitEvent:
    """A wait for a rate-limit token."""

    source_system: str
    lane: str
    seconds: float


@dataclass(frozen=True, slots=True)
class RetryEvent:
    """A scheduled retry, with its reason and delay."""

    source_system: str
    endpoint: str
    reason: str
    delay_s: float


@dataclass(frozen=True, slots=True)
class DeferredEvent:
    """A call deferred until a later time."""

    source_system: str
    endpoint: str
    retry_at: datetime


@dataclass(frozen=True, slots=True)
class DeadLetterEvent:
    """A call given up on after its retries ran out."""

    source_system: str
    endpoint: str
    reason: str


class Observer(Protocol):
    """Receives runtime events, for metrics and tracing."""

    def attempt(
        self,
        *,
        source_system: str,
        endpoint: str,
        status: str | None,
        latency_ms: float,
        retry_count: int,
        error_type: str | None,
    ) -> None:
        """Record one call attempt."""

    def rate_wait(self, *, source_system: str, lane: str, seconds: float) -> None:
        """Record a wait for a rate-limit token."""

    def retry(self, *, source_system: str, endpoint: str, reason: str, delay_s: float) -> None:
        """Record a scheduled retry."""

    def deferred(self, *, source_system: str, endpoint: str, retry_at: datetime) -> None:
        """Record a deferral."""

    def dead_letter(self, *, source_system: str, endpoint: str, reason: str) -> None:
        """Record a dead letter."""


class NoOpObserver:
    """Discards every event. The production default until a real observer exists."""

    def attempt(
        self,
        *,
        source_system: str,
        endpoint: str,
        status: str | None,
        latency_ms: float,
        retry_count: int,
        error_type: str | None,
    ) -> None:
        """Ignore the event."""
        return

    def rate_wait(self, *, source_system: str, lane: str, seconds: float) -> None:
        """Ignore the event."""
        return

    def retry(self, *, source_system: str, endpoint: str, reason: str, delay_s: float) -> None:
        """Ignore the event."""
        return

    def deferred(self, *, source_system: str, endpoint: str, retry_at: datetime) -> None:
        """Ignore the event."""
        return

    def dead_letter(self, *, source_system: str, endpoint: str, reason: str) -> None:
        """Ignore the event."""
        return


@dataclass
class ListObserver:
    """Collects every event, in order, for tests to assert against `.events`."""

    events: list[AttemptEvent | RateWaitEvent | RetryEvent | DeferredEvent | DeadLetterEvent] = field(
        default_factory=list
    )

    def attempt(
        self,
        *,
        source_system: str,
        endpoint: str,
        status: str | None,
        latency_ms: float,
        retry_count: int,
        error_type: str | None,
    ) -> None:
        """Append the event to `events`."""
        self.events.append(AttemptEvent(source_system, endpoint, status, latency_ms, retry_count, error_type))

    def rate_wait(self, *, source_system: str, lane: str, seconds: float) -> None:
        """Append the event to `events`."""
        self.events.append(RateWaitEvent(source_system, lane, seconds))

    def retry(self, *, source_system: str, endpoint: str, reason: str, delay_s: float) -> None:
        """Append the event to `events`."""
        self.events.append(RetryEvent(source_system, endpoint, reason, delay_s))

    def deferred(self, *, source_system: str, endpoint: str, retry_at: datetime) -> None:
        """Append the event to `events`."""
        self.events.append(DeferredEvent(source_system, endpoint, retry_at))

    def dead_letter(self, *, source_system: str, endpoint: str, reason: str) -> None:
        """Append the event to `events`."""
        self.events.append(DeadLetterEvent(source_system, endpoint, reason))
