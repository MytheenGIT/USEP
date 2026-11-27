"""Delete reconciliation: find objects that were landed earlier but are no longer listed by the source, and tombstone them.

Why: an incremental poll only ever sees objects that changed. A deletion, or an object leaving a scope, or one the
integration user can no longer see, never shows up as a change. So a scheduled run lists the ids a scope holds now and
compares them with the object index (ids landed per source and scope). The difference gets a `tombstone.<source>` event.

Safety. A listing can come back empty or short for reasons that are not deletions (an expired token that returns an empty
page, a permission change, an API hiccup). Wrongly tombstoning a whole scope would remove good evidence, so:
  * a listing that raises is reported and nothing is tombstoned for that scope;
  * when at least ``guard_min_known`` objects are known and more than ``max_missing_fraction`` of them are missing, the
    scope is refused and reported, and a person decides;
  * ids are removed from the index only after their tombstone was published, so a failed publish is retried next run.
A scope with no index entry (data landed before the index existed) tombstones nothing.

Sources whose connector has no ``list_ids`` (Figma) are skipped and reported as unsupported.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from common.interfaces.object_index import ObjectIndex
from common.interfaces.raw_event_publisher import RawEventPublisher
from sync_service import cursor_key

logger = structlog.get_logger(__name__)
REASON = "not_found_in_scope"       # deleted, moved out of the scope, or no longer visible to the integration user


@dataclass
class ScopeReport:
    scope: str
    status: str                     # ok | refused | error | unsupported | empty_index
    known: int = 0
    listed: int = 0
    tombstoned: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class ReconcileResult:
    source: str
    scopes: list[ScopeReport] = field(default_factory=list)

    @property
    def tombstoned(self) -> int:
        return sum(len(s.tombstoned) for s in self.scopes)

    @property
    def problems(self) -> list[ScopeReport]:
        return [s for s in self.scopes if s.status in ("refused", "error")]

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "tombstoned": self.tombstoned,
                "scopes": [{"scope": s.scope, "status": s.status, "known": s.known, "listed": s.listed,
                            "tombstoned": len(s.tombstoned), "detail": s.detail} for s in self.scopes]}


class Reconciler:
    def __init__(self, connectors: dict[str, Any], object_index: ObjectIndex, publisher: RawEventPublisher,
                 max_missing_fraction: float = 0.3, guard_min_known: int = 10) -> None:
        self._connectors, self._index, self._publisher = connectors, object_index, publisher
        self._max_fraction, self._guard_min = max_missing_fraction, guard_min_known

    async def reconcile_source(self, source: str, scopes: list[str] | None = None) -> ReconcileResult:
        connector = self._connectors.get(source)
        if connector is None:
            raise ValueError(f"No connector registered for source '{source}'")
        result = ReconcileResult(source)
        for scope in scopes if scopes is not None else list(connector.scopes):
            result.scopes.append(await self._reconcile_scope(source, connector, scope))
        return result

    async def _reconcile_scope(self, source: str, connector: Any, scope: str) -> ScopeReport:
        if not hasattr(connector, "list_ids"):
            return ScopeReport(scope, "unsupported", detail=f"{source} cannot list its objects")
        key = cursor_key(source, scope)
        known = await self._index.get(key)
        if not known:
            return ScopeReport(scope, "empty_index", detail="nothing landed for this scope yet")
        try:
            listed = set(await connector.list_ids(scope))
        except Exception as exc:  # noqa: BLE001 - an unreadable scope is never evidence of deletion
            logger.warning("reconcile.list_failed", source=source, scope=scope, error=str(exc))
            return ScopeReport(scope, "error", known=len(known), detail=f"listing failed: {exc}")
        missing = sorted(known - listed)
        report = ScopeReport(scope, "ok", known=len(known), listed=len(listed))
        if missing and len(known) >= self._guard_min and len(missing) / len(known) > self._max_fraction:
            report.status = "refused"
            report.detail = (f"{len(missing)} of {len(known)} known objects are missing, above "
                             f"{self._max_fraction:.0%}: looks like an auth or listing problem, not deletions")
            logger.error("reconcile.refused", source=source, scope=scope, missing=len(missing), known=len(known))
            return report
        done: set[str] = set()
        try:
            for sid in missing:
                await self._publisher.publish_tombstone(source, sid, scope, REASON)
                done.add(sid)
        finally:                                    # only what was announced leaves the index; the rest retries next run
            await self._index.remove(key, done)
            report.tombstoned = sorted(done)
        return report
