"""`ReconciliationDiff` and the tombstone decision (LLD §4.2; D14)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class ReconciliationDiff:
    missing: frozenset[str]  # object_ids in source, not stored
    extra: frozenset[str]  # object_ids stored, not in source
    stale: frozenset[str]  # object_ids whose stored version differs from the source's


def diff(
    source_ids: frozenset[str],
    source_versions: dict[str, str],
    stored_ids: frozenset[str],
    stored_versions: dict[str, str],
) -> ReconciliationDiff:
    """Missing, extra and stale sets (LLD §4.2). Staleness is a version *mismatch*,
    not an ordering comparison — the cursor/version encoding is opaque to this layer
    (section 5.4), so any difference from the source's reported version is treated
    as stale and refetched; this is conservative (it can refetch an object whose
    stored version happens to be newer, which a correct connector should not
    produce) rather than risk missing a real update by trying to order values whose
    type this layer does not know.
    """
    missing = source_ids - stored_ids
    extra = stored_ids - source_ids
    stale = frozenset(
        object_id
        for object_id in (source_ids & stored_ids)
        if stored_versions.get(object_id) != source_versions.get(object_id)
    )
    return ReconciliationDiff(missing=missing, extra=extra, stale=stale)


def should_tombstone(
    *,
    first_seen_extra_at: datetime | None,
    now: datetime,
    min_age_seconds: int,
    still_absent: bool,
) -> bool:
    """D14: tombstone only when `first_seen_extra_at` is at least `min_age_seconds`
    old (default 72000s = 20h) *and* the object is still absent from the source on
    this run — so a transient API gap can never delete data on its own."""
    if first_seen_extra_at is None or not still_absent:
        return False
    return (now - first_seen_extra_at) >= timedelta(seconds=min_age_seconds)
