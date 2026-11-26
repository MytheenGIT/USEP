"""Cursor manager: the overlap window and the batch-advance rule. Generic — no
source-specific cursor encoding here. Uses the exact `CursorStorePort`
(`get_cursor`/`set_cursor`, no version parameter — see ports/cursor_store.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from usep.ingestion.ports.cursor_store import CursorStorePort

_RESOLVED_OUTCOMES = frozenset({"written", "skipped_unchanged", "quarantined", "deferred"})


def effective_cursor(cursor_value: str | None, overlap_seconds: int) -> str | None:
    """`cursor - overlap_seconds` when the cursor parses as an ISO-8601 timestamp;
    returned unchanged otherwise (the cursor's encoding is opaque in general — a
    commit SHA, for example, has no overlap arithmetic that applies to it)."""
    if cursor_value is None or overlap_seconds <= 0:
        return cursor_value
    try:
        parsed = datetime.fromisoformat(cursor_value.replace("Z", "+00:00"))
    except ValueError:
        return cursor_value
    return (parsed - timedelta(seconds=overlap_seconds)).isoformat()


@dataclass(frozen=True, slots=True)
class Batch:
    source: str
    fetch_from: str | None


class CursorManager:
    def __init__(self, store: CursorStorePort, *, overlap_seconds: int = 300) -> None:
        self._store = store
        self._overlap_seconds = overlap_seconds

    async def start_batch(self, source: str) -> Batch:
        cursor_value = await self._store.get_cursor(source)
        return Batch(source=source, fetch_from=effective_cursor(cursor_value, self._overlap_seconds))

    async def advance(self, batch: Batch, new_cursor: str, outcomes: list[str]) -> None:
        """Advances the cursor only if every object in the batch reached a
        resolved outcome (written, published, quarantined, or deferred) — never
        past an object still pending."""
        unresolved = [o for o in outcomes if o not in _RESOLVED_OUTCOMES]
        if unresolved:
            raise ValueError(f"cannot advance cursor: unresolved outcomes {unresolved}")
        await self._store.set_cursor(batch.source, new_cursor)
