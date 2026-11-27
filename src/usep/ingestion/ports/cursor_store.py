"""`CursorStorePort`: matches the connectors branch's `CursorManager` protocol.

It matches the connectors branch's `CursorManager` Protocol exactly: `get_cursor(source)` and
`set_cursor(source, cursor)`.

`tenant_id` is bound at adapter construction, not passed per call.

No optimistic-version parameter: the exact Protocol has no room for one, so
concurrent-writer conflict detection (sketched in an earlier pass of this work)
is dropped rather than added back as an extra argument. See
docs/plans/ASSUMPTIONS.md.
"""

from __future__ import annotations

from typing import Protocol


class CursorStorePort(Protocol):
    """Persists the sync cursor of each source."""

    async def get_cursor(self, source: str) -> str | None:
        """Return the last saved cursor for `source`, or `None` for a full sync.

        The cursor is read within this adapter's bound tenant.
        """
        ...

    async def set_cursor(self, source: str, cursor: str) -> None:
        """Persists the new cursor for `source` after a successful sync."""
        ...
