"""Object store port: where the pipeline reads raw snapshots and writes evidence and quarantine records."""
from __future__ import annotations

from typing import Protocol


class ObjectStore(Protocol):
    def get(self, ref: str) -> bytes:
        """Read by reference ('s3://bucket/key'). Raises if missing."""
        ...

    def put_if_absent(self, key: str, body: bytes) -> str:
        """Write once and return the reference. An existing object with the same key is left as it is (immutable)."""
        ...
