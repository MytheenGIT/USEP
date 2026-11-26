"""`ObjectStorePort`: raw-object byte storage (section 5.2, 5.5)."""

from __future__ import annotations

from typing import Protocol


class ObjectStorePort(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def exists(self, key: str) -> bool: ...
