"""Contract for the Object Index: which object ids have been landed for each cursor key (source and scope).

Reconciliation compares this set with what the source lists now. An id that was landed and is no longer listed has been
deleted at the source (or has left the scope, or become invisible to the integration user), and gets a tombstone event.
The default is in memory only; the S3 implementation persists one small object per cursor key.
"""
from __future__ import annotations

from typing import Protocol


class ObjectIndex(Protocol):
    async def get(self, key: str) -> set[str]: ...

    async def add(self, key: str, ids: set[str]) -> None: ...

    async def remove(self, key: str, ids: set[str]) -> None: ...


class InMemoryObjectIndex:
    def __init__(self) -> None:
        self._ids: dict[str, set[str]] = {}

    async def get(self, key: str) -> set[str]:
        return set(self._ids.get(key, set()))

    async def add(self, key: str, ids: set[str]) -> None:
        self._ids.setdefault(key, set()).update(ids)

    async def remove(self, key: str, ids: set[str]) -> None:
        self._ids.setdefault(key, set()).difference_update(ids)
