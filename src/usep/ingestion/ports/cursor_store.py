"""`CursorStorePort`: matches the connectors branch's `CursorManager` Protocol
exactly (`get_cursor(source)` / `set_cursor(source, cursor)`). `tenant_id` is
bound at adapter construction, not passed per call.

No optimistic-version parameter: the exact Protocol has no room for one, so
concurrent-writer conflict detection (sketched in an earlier pass of this work)
is dropped rather than added back as an extra argument. See
docs/plans/ASSUMPTIONS.md.
"""

from __future__ import annotations

from typing import Protocol


class CursorStorePort(Protocol):
    async def get_cursor(self, source: str) -> str | None:
        """The last persisted cursor for `source` (within this adapter's bound
        tenant), or `None` for a full sync."""
        ...

    async def set_cursor(self, source: str, cursor: str) -> None:
        """Persists the new cursor for `source` after a successful sync."""
        ...
