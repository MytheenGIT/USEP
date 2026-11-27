"""The clock port and its default, real-time implementation.

Every timestamp USEP records is UTC, ISO-8601, millisecond precision (ground rule,
section 1). Domain and runtime code never call `datetime.now()` directly — they take
a `Clock` so tests can inject a fake and assert on exact, reproducible timestamps
(for example the back-off delay sequence, or the 5-minute/10-minute state-machine
timers in section 5.3).
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol


def _truncate_to_milliseconds(value: dt.datetime) -> dt.datetime:
    """Drop sub-millisecond precision so every stored or compared timestamp is exact to 1ms."""
    microsecond = (value.microsecond // 1000) * 1000
    return value.replace(microsecond=microsecond)


class Clock(Protocol):
    """A source of the current UTC time, millisecond precision."""

    def now(self) -> dt.datetime: ...


class SystemClock:
    """The real wall clock. The only `Clock` implementation used outside tests."""

    def now(self) -> dt.datetime:
        return _truncate_to_milliseconds(dt.datetime.now(dt.UTC))
