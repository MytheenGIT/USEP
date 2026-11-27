"""Cursors held in memory: for runs that must start from scratch every time (a console configuration is read in full)."""

from __future__ import annotations


class InMemoryCursorStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    async def get_cursor(self, source: str) -> str | None:
        return self._values.get(source)

    async def set_cursor(self, source: str, cursor: str) -> None:
        self._values[source] = cursor
