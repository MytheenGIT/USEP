"""Reconciliation: generic, source-agnostic. Missing and stale objects are
surfaced for immediate re-fetch; an object the source no longer reports is
tombstoned only after a second, later confirmation at least 20 hours after it was
first seen extra.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from usep.ingestion.domain.raw_object import RawObjectRef
from usep.ingestion.domain.reconciliation import ReconciliationDiff, diff, should_tombstone
from usep.ingestion.ports.raw_index import RawIndexPort

DEFAULT_TOMBSTONE_MIN_AGE_SECONDS = 72_000  # 20 hours


async def reconcile_scope(
    raw_index: RawIndexPort,
    *,
    tenant_id: UUID,
    source: str,
    scope_id: str,
    source_ids: frozenset[str],
    source_versions: dict[str, str],
    now: datetime | None = None,
    tombstone_min_age_seconds: int = DEFAULT_TOMBSTONE_MIN_AGE_SECONDS,
) -> ReconciliationDiff:
    """Compares the source's current object/version listing against what's
    stored for this scope. Missing and stale object_ids are returned for the
    caller to fetch immediately on the live lane (fetching itself is
    source-specific and out of scope here). Extra objects get
    `first_seen_extra_at` set on first sight, and are tombstoned (crypto-shred)
    only once that timestamp is at least `tombstone_min_age_seconds` old and the
    object is still absent on this run.
    """
    at = now or datetime.now(UTC)
    stored_refs: dict[str, RawObjectRef] = {}
    for ref in await raw_index.list_extant_by_scope(tenant_id, source, scope_id):
        stored_refs.setdefault(ref.object_id, ref)  # most recent content_hash per object_id, if more than one

    stored_versions = {object_id: ref.content_hash for object_id, ref in stored_refs.items()}
    result = diff(source_ids, source_versions, frozenset(stored_refs), stored_versions)

    for object_id in result.extra:
        ref = stored_refs[object_id]
        if ref.first_seen_extra_at is None:
            await raw_index.mark_first_seen_extra(ref, at=at)
        elif should_tombstone(
            first_seen_extra_at=ref.first_seen_extra_at,
            now=at,
            min_age_seconds=tombstone_min_age_seconds,
            still_absent=True,
        ):
            await raw_index.tombstone(ref, at=at)

    return result
