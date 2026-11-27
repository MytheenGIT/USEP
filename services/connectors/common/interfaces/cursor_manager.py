"""Contract for the Sync Cursor Manager.

Ownership: implemented elsewhere. This module defines the interface the
ingestion layer depends on and ships a trivial in-process default
(``InMemoryCursorManager``) only so the service is runnable in isolation
(local dev / tests). It persists nothing and must be replaced by the real
implementation (e.g. backed by Postgres) before this runs anywhere shared.
"""

from __future__ import annotations

from typing import Protocol


class CursorManager(Protocol):
    """Tracks per-source resume cursors (last-seen timestamp/page/etc.)."""

    async def get_cursor(self, source: str) -> str | None:
        """Return the last persisted cursor for ``source``, or None for a full sync."""
        ...

    async def set_cursor(self, source: str, cursor: str) -> None:
        """Persist the new cursor for ``source`` after a successful sync."""
        ...


class InMemoryCursorManager:
    """Non-persistent default so the ingestion service can run standalone."""

    def __init__(self) -> None:
        self._cursors: dict[str, str] = {}

    async def get_cursor(self, source: str) -> str | None:
        return self._cursors.get(source)

    async def set_cursor(self, source: str, cursor: str) -> None:
        self._cursors[source] = cursor
