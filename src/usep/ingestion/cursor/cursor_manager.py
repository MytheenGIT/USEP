"""Cursor manager: the overlap window and the batch-advance rule.

Generic — no source-specific cursor encoding here. Uses the exact `CursorStorePort`
(`get_cursor`/`set_cursor`, no version parameter — see ports/cursor_store.py).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from usep.ingestion.domain.outcome import Outcome
from usep.ingestion.ports.cursor_store import CursorStorePort

DEFAULT_OVERLAP_SECONDS = 300
_RESOLVED_OUTCOMES = frozenset(
    {Outcome.WRITTEN, Outcome.SKIPPED_UNCHANGED, Outcome.QUARANTINED, Outcome.DEFERRED}
)


def effective_cursor(cursor_value: str | None, overlap_seconds: int) -> str | None:
    """Return the cursor moved back by the overlap, when it is a timestamp.

    The cursor's encoding is opaque in general: a value that is not an ISO-8601 timestamp, such as a
    commit SHA, is returned unchanged.
    """
    if cursor_value is None or overlap_seconds <= 0:
        return cursor_value
    if "-" not in cursor_value:
        return cursor_value  # fromisoformat also accepts an opaque ID such as "20260101" as a date
    try:
        parsed = datetime.fromisoformat(cursor_value)
    except ValueError:
        return cursor_value
    return (parsed - timedelta(seconds=overlap_seconds)).isoformat()


@dataclass(frozen=True, slots=True)
class Batch:
    """One fetch batch: the source and the cursor to fetch from.

    `fetch_from` is already moved back by the overlap.
    """

    source: str
    fetch_from: str | None


class CursorManager:
    """Tracks how far each source has been synced and decides when the cursor may move forward."""

    def __init__(self, store: CursorStorePort, *, overlap_seconds: int = DEFAULT_OVERLAP_SECONDS) -> None:
        """Build the manager.

        Args:
            store: Where cursors are saved.
            overlap_seconds: How far before the saved cursor the next fetch starts.
        """
        self._store = store
        self._overlap_seconds = overlap_seconds

    async def start_batch(self, source: str) -> Batch:
        """Start a batch for a source.

        Args:
            source: Source system name.

        Returns:
            A batch whose `fetch_from` is the saved cursor minus the overlap, or `None` for a full sync.
        """
        cursor_value = await self._store.get_cursor(source)
        return Batch(source=source, fetch_from=effective_cursor(cursor_value, self._overlap_seconds))

    async def advance(self, batch: Batch, new_cursor: str, outcomes: Iterable[Outcome]) -> None:
        """Move the cursor forward only if every object in the batch is resolved.

        Resolved outcomes are written, skipped as unchanged, quarantined and deferred. The cursor
        never moves past an object that is still pending or has failed.
        """
        unresolved = [o for o in outcomes if o not in _RESOLVED_OUTCOMES]
        if unresolved:
            raise ValueError(f"cannot advance cursor: unresolved outcomes {[str(o) for o in unresolved]}")
        await self._store.set_cursor(batch.source, new_cursor)
