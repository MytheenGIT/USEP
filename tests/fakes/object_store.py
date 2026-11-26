from __future__ import annotations


class InMemoryObjectStore:
    """Fake `ObjectStorePort`. Never imported from production code."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def exists(self, key: str) -> bool:
        return key in self.objects
