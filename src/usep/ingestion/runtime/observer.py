"""The observer port: one event per attempt, rate-limit wait, retry, deferral and
dead letter (section 5.7, 8). `NoOpObserver` is the production default until a real
metrics/tracing observer is wired in a later phase; `ListObserver` lets tests assert
on exactly what happened without needing a real collector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AttemptEvent:
    source_system: str
    endpoint: str
    status: str | None
    latency_ms: float
    retry_count: int
    error_type: str | None


@dataclass(frozen=True, slots=True)
class RateWaitEvent:
    source_system: str
    lane: str
    seconds: float


@dataclass(frozen=True, slots=True)
class RetryEvent:
    source_system: str
    endpoint: str
    reason: str
    delay_s: float


@dataclass(frozen=True, slots=True)
class DeferredEvent:
    source_system: str
    endpoint: str
    retry_at: datetime


@dataclass(frozen=True, slots=True)
class DeadLetterEvent:
    source_system: str
    endpoint: str
    reason: str


class Observer(Protocol):
    def attempt(
        self,
        *,
        source_system: str,
        endpoint: str,
        status: str | None,
        latency_ms: float,
        retry_count: int,
        error_type: str | None,
    ) -> None: ...

    def rate_wait(self, *, source_system: str, lane: str, seconds: float) -> None: ...

    def retry(self, *, source_system: str, endpoint: str, reason: str, delay_s: float) -> None: ...

    def deferred(self, *, source_system: str, endpoint: str, retry_at: datetime) -> None: ...

    def dead_letter(self, *, source_system: str, endpoint: str, reason: str) -> None: ...


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
        return None

    def rate_wait(self, *, source_system: str, lane: str, seconds: float) -> None:
        return None

    def retry(self, *, source_system: str, endpoint: str, reason: str, delay_s: float) -> None:
        return None

    def deferred(self, *, source_system: str, endpoint: str, retry_at: datetime) -> None:
        return None

    def dead_letter(self, *, source_system: str, endpoint: str, reason: str) -> None:
        return None


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
        self.events.append(AttemptEvent(source_system, endpoint, status, latency_ms, retry_count, error_type))

    def rate_wait(self, *, source_system: str, lane: str, seconds: float) -> None:
        self.events.append(RateWaitEvent(source_system, lane, seconds))

    def retry(self, *, source_system: str, endpoint: str, reason: str, delay_s: float) -> None:
        self.events.append(RetryEvent(source_system, endpoint, reason, delay_s))

    def deferred(self, *, source_system: str, endpoint: str, retry_at: datetime) -> None:
        self.events.append(DeferredEvent(source_system, endpoint, retry_at))

    def dead_letter(self, *, source_system: str, endpoint: str, reason: str) -> None:
        self.events.append(DeadLetterEvent(source_system, endpoint, reason))
