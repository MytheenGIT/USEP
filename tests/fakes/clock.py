from __future__ import annotations

import datetime as dt


class FakeClock:
    """A controllable clock for tests: `.now()` returns the current fake time;
    `.advance()` moves it forward. Never used outside tests."""

    def __init__(self, start: dt.datetime | None = None) -> None:
        self._now = start or dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

    def now(self) -> dt.datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += dt.timedelta(seconds=seconds)
