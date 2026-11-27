from __future__ import annotations

from uuid import UUID


class InMemoryCursorStore:
    """Fake `CursorStorePort`. `tenant_id` bound at construction, matching the
    real adapter. Never imported from production code."""

    def __init__(self, tenant_id: UUID) -> None:
        self._tenant_id = tenant_id
        self._cursors: dict[str, str] = {}

    async def get_cursor(self, source: str) -> str | None:
        return self._cursors.get(source)

    async def set_cursor(self, source: str, cursor: str) -> None:
        self._cursors[source] = cursor
