"""`ObjectStorePort`: raw-object byte storage (section 5.2, 5.5)."""

from __future__ import annotations

from typing import Protocol


class ObjectStorePort(Protocol):
    """Stores raw-object bytes by key."""

    async def put(self, key: str, content: bytes) -> None:
        """Store `content` under `key`, replacing anything already there."""

    async def get(self, key: str) -> bytes:
        """Return the bytes stored under `key`."""

    async def exists(self, key: str) -> bool:
        """Return whether anything is stored under `key`."""
