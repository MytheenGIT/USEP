"""Reconciliation: generic, source-agnostic.

Missing and stale objects are surfaced for immediate re-fetch; an object the source no longer
reports is tombstoned only after a second, later confirmation at least 20 hours after it was first
seen extra.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from usep.core.defaults import DEFAULT_TOMBSTONE_MIN_AGE_S
from usep.ingestion.domain.raw_object import RawObjectRef
from usep.ingestion.domain.reconciliation import ReconciliationDiff, diff, should_tombstone
from usep.ingestion.ports.raw_index import RawIndexPort

logger = logging.getLogger(__name__)


async def reconcile_scope(
    raw_index: RawIndexPort,
    *,
    tenant_id: UUID,
    source: str,
    scope_id: str,
    source_ids: frozenset[str],
    source_versions: dict[str, str],
    now: datetime,
    tombstone_min_age_seconds: int = DEFAULT_TOMBSTONE_MIN_AGE_S,
) -> ReconciliationDiff:
    """Compares the source's current object/version listing against what's stored for this scope.

    Missing and stale object_ids are returned for the caller to fetch immediately on the live lane
    (fetching itself is source-specific and out of scope here). Extra objects get
    `first_seen_extra_at` set on first sight, and every stored version of one is tombstoned
    (crypto-shred) only once that timestamp is at least `tombstone_min_age_seconds` old and the
    object is still absent on this run. An object that is back in the source has its earlier absence
    forgotten.

    A listing with no objects at all, for a scope that has stored objects, is treated as lost
    access or a source fault, not as a mass deletion: nothing is marked or tombstoned and a
    warning is logged. Removing a whole scope belongs to the scope-removal workflow.

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
    versions_by_object = _group_by_object(await raw_index.list_extant_by_scope(tenant_id, source, scope_id))

    # The newest stored version is the one compared with the source; older ones are history.
    current = {
        object_id: max(refs, key=lambda r: r.imported_at) for object_id, refs in versions_by_object.items()
    }
    stored_versions = {object_id: ref.source_version for object_id, ref in current.items()}
    result = diff(source_ids, source_versions, frozenset(current), stored_versions)

    if not source_ids and current:
        # shortcut: a scope whose objects were all really deleted is never shredded here, because the
        # scope-removal workflow does not exist yet; upgrade once it does (HLD 24-hour deletion rule).
        logger.warning(
            "reconcile skipped: source listed no objects for a scope with stored objects",
            extra={"source": source, "scope_id": scope_id, "stored_objects": len(current)},
        )
        return result

    for object_id in source_ids & current.keys():
        if current[object_id].first_seen_extra_at is not None:
            await raw_index.clear_first_seen_extra(current[object_id])

    for object_id in result.extra:
        await _mark_or_tombstone(
            raw_index, current[object_id], versions_by_object[object_id], now, tombstone_min_age_seconds
        )

    return result


def _group_by_object(refs: list[RawObjectRef]) -> dict[str, list[RawObjectRef]]:
    """Group index rows by object ID, so every stored version of an object is found together."""
    grouped: dict[str, list[RawObjectRef]] = {}
    for ref in refs:
        grouped.setdefault(ref.object_id, []).append(ref)
    return grouped


async def _mark_or_tombstone(
    raw_index: RawIndexPort,
    current: RawObjectRef,
    versions: list[RawObjectRef],
    now: datetime,
    min_age_seconds: int,
) -> None:
    """Mark an absent object on first sight; tombstone every version once the absence is confirmed."""
    if current.first_seen_extra_at is None:
        await raw_index.mark_first_seen_extra(current, at=now)
    elif should_tombstone(
        first_seen_extra_at=current.first_seen_extra_at,
        now=now,
        min_age_seconds=min_age_seconds,
        still_absent=True,
    ):
        for version in versions:
            await raw_index.tombstone(version, at=now)
