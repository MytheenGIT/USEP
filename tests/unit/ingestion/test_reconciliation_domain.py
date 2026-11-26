from __future__ import annotations

import datetime as dt

from usep.ingestion.domain.reconciliation import diff, should_tombstone


def test_diff_computes_missing_extra_and_stale() -> None:
    source_ids = frozenset({"a", "b", "c"})
    source_versions = {"a": "v1", "b": "v2", "c": "v1"}
    stored_ids = frozenset({"b", "c", "d"})
    stored_versions = {"b": "v1", "c": "v1", "d": "v1"}  # b is stale (v1 != v2)

    result = diff(source_ids, source_versions, stored_ids, stored_versions)
    assert result.missing == frozenset({"a"})
    assert result.extra == frozenset({"d"})
    assert result.stale == frozenset({"b"})


def test_should_tombstone_requires_min_age_and_still_absent() -> None:
    now = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    first_seen = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)  # 24h ago

    assert should_tombstone(
        first_seen_extra_at=first_seen, now=now, min_age_seconds=72_000, still_absent=True
    )
    # Not old enough yet (20h = 72000s required; this is exactly 24h, so it passes;
    # check a case that is NOT old enough):
    recent = now - dt.timedelta(hours=1)
    assert not should_tombstone(
        first_seen_extra_at=recent, now=now, min_age_seconds=72_000, still_absent=True
    )
    # Reappeared on this run: never tombstone even if old enough.
    assert not should_tombstone(
        first_seen_extra_at=first_seen, now=now, min_age_seconds=72_000, still_absent=False
    )
    # Never flagged as extra before: nothing to tombstone.
    assert not should_tombstone(first_seen_extra_at=None, now=now, min_age_seconds=72_000, still_absent=True)
