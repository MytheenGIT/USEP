from __future__ import annotations

import datetime as dt

from usep.core.clock import SystemClock
from usep.core.ids import new_id


def test_new_id_is_version_7() -> None:
    generated = new_id()
    assert generated.version == 7


def test_new_id_is_time_ordered() -> None:
    first = new_id()
    second = new_id()
    assert first.bytes[:6] <= second.bytes[:6]


def test_system_clock_is_utc_and_millisecond_precision() -> None:
    clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is not None
    assert now.utcoffset() == dt.timedelta(0)
    assert now.microsecond % 1000 == 0
