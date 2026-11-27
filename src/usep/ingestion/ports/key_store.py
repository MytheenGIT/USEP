"""`KeyEncryptionPort`: wraps and unwraps per-object data keys using KMS (D2).

The per-object key is an AES-256-GCM data key. The key-encryption key is per tenant and held in KMS
(D2).

No `destroy` method: erasure of a single object is `RawIndexPort.tombstone()`
clearing that object's own `wrapped_dek` row — the tenant's key-encryption key
itself is never destroyed by an object-level erasure, since other objects still
depend on it.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class KeyEncryptionPort(Protocol):
    """Wraps and unwraps per-object data keys with a per-tenant key-encryption key."""

    async def wrap(self, tenant_id: UUID, data_key: bytes) -> tuple[bytes, str]:
        """Returns `(wrapped_data_key, kek_id)`."""
        ...

    async def unwrap(self, tenant_id: UUID, wrapped_data_key: bytes, kek_id: str) -> bytes:
        """Return the data key that a wrapped key protects.

        Args:
            tenant_id: Tenant that owns the key-encryption key.
            wrapped_data_key: The wrapped key, as returned by `wrap`.
            kek_id: Identifier of the key-encryption key that wrapped it.

        Returns:
            The plain data key.
        """
