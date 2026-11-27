"""Reconciliation: generic, source-agnostic. Missing and stale objects are
surfaced for immediate re-fetch; an object the source no longer reports is
tombstoned only after a second, later confirmation at least 20 hours after it was
first seen extra.
"""

from __future__ import annotations

from datetime import datetime
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
    now: datetime,
    tombstone_min_age_seconds: int = DEFAULT_TOMBSTONE_MIN_AGE_SECONDS,
) -> ReconciliationDiff:
    """Compares the source's current object/version listing against what's
    stored for this scope. Missing and stale object_ids are returned for the
    caller to fetch immediately on the live lane (fetching itself is
    source-specific and out of scope here). Extra objects get
    `first_seen_extra_at` set on first sight, and every stored version of one is
    tombstoned (crypto-shred) only once that timestamp is at least
    `tombstone_min_age_seconds` old and the object is still absent on this run.
    An object that is back in the source has its earlier absence forgotten.

    Args:
        raw_index: The raw-object index for this tenant.
        tenant_id: Tenant whose objects are compared.
        source: Source system name.
        scope_id: Scope within the source.
        source_ids: Every object_id the source currently lists in this scope.
        source_versions: The source's version for each object_id.
        now: Current time, supplied by the caller's `Clock`.
        tombstone_min_age_seconds: Minimum time between first and confirming absence.

    Returns:
        The missing, extra and stale object_id sets.
    """
    versions_by_object: dict[str, list[RawObjectRef]] = {}
    for ref in await raw_index.list_extant_by_scope(tenant_id, source, scope_id):
        versions_by_object.setdefault(ref.object_id, []).append(ref)

    # The newest stored version is the one compared with the source; older ones are history.
    current = {
        object_id: max(refs, key=lambda r: r.imported_at) for object_id, refs in versions_by_object.items()
    }
    stored_versions = {object_id: ref.content_hash for object_id, ref in current.items()}
    result = diff(source_ids, source_versions, frozenset(current), stored_versions)

    for object_id in source_ids & current.keys():
        if current[object_id].first_seen_extra_at is not None:
            await raw_index.clear_first_seen_extra(current[object_id])

    for object_id in result.extra:
        ref = current[object_id]
        if ref.first_seen_extra_at is None:
            await raw_index.mark_first_seen_extra(ref, at=now)
        elif should_tombstone(
            first_seen_extra_at=ref.first_seen_extra_at,
            now=now,
            min_age_seconds=tombstone_min_age_seconds,
            still_absent=True,
        ):
            for version in versions_by_object[object_id]:
                await raw_index.tombstone(version, at=now)

    return result
