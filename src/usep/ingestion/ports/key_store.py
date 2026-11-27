"""`KeyEncryptionPort`: wraps/unwraps a per-object AES-256-GCM data key with a
per-tenant key-encryption key held in KMS (D2).

No `destroy` method: erasure of a single object is `RawIndexPort.tombstone()`
clearing that object's own `wrapped_dek` row — the tenant's key-encryption key
itself is never destroyed by an object-level erasure, since other objects still
depend on it.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class KeyEncryptionPort(Protocol):
    async def wrap(self, tenant_id: UUID, data_key: bytes) -> tuple[bytes, str]:
        """Returns `(wrapped_data_key, kek_id)`."""
        ...

    async def unwrap(self, tenant_id: UUID, wrapped_data_key: bytes, kek_id: str) -> bytes: ...
