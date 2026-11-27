from __future__ import annotations

import datetime as dt
import random

import pytest

from usep.ingestion.runtime.backoff import compute_delay, parse_retry_after


def test_backoff_sequence_and_cap() -> None:
    """CC-03: base 2s, doubling, capped at 600s, across the full retry sequence."""
    rng = random.Random(0)
    expected_ceilings = [2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 512.0, 600.0, 600.0]
    for attempt, ceiling in enumerate(expected_ceilings, start=1):
        delay = compute_delay(attempt, base_delay_s=2.0, max_delay_s=600.0, rng=rng)
        assert 0 <= delay <= ceiling


def test_compute_delay_rejects_non_positive_attempt() -> None:
    with pytest.raises(ValueError):
        compute_delay(0, base_delay_s=2.0, max_delay_s=600.0)


def test_retry_after_within_cap_honoured() -> None:
    """CC-03: Retry-After given as delay-seconds, within the cap, parses exactly."""
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    assert parse_retry_after("120", now=now) == 120.0


def test_retry_after_http_date_parses_to_seconds_from_now() -> None:
    now = dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    future = now + dt.timedelta(seconds=90)
    http_date = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
    seconds = parse_retry_after(http_date, now=now)
    assert seconds is not None
    assert 89.0 <= seconds <= 90.0


def test_retry_after_unparseable_returns_none() -> None:
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    assert parse_retry_after("not-a-valid-value", now=now) is None
    assert parse_retry_after("", now=now) is None


def test_retry_after_with_non_ascii_digits_is_unparseable_not_a_crash() -> None:
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    assert parse_retry_after("\u00b2", now=now) is None
