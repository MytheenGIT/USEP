"""`KeyEncryptionPort` with a key-encryption key held in process memory.

DEVELOPMENT ONLY. The HLD wants the tenant key in Vault or a KMS (open item O-04: key
management design and its ADR). Until that is decided, this wraps each data key with
AES-256-GCM under one local key so the raw payload writer can run end to end. Replace it
with the Vault or KMS adapter before any real data is stored.
"""

from __future__ import annotations

import os
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from usep.core.errors import ConfigError

KEK_ID = "local-dev-kek-v1"
_NONCE_SIZE = 12


class LocalKeyEncryption:
    def __init__(self, kek: bytes) -> None:
        if len(kek) != 32:
            raise ConfigError("the local key-encryption key must be exactly 32 bytes")
        self._aead = AESGCM(kek)

    async def wrap(self, tenant_id: UUID, data_key: bytes) -> tuple[bytes, str]:
        nonce = os.urandom(_NONCE_SIZE)
        return nonce + self._aead.encrypt(nonce, data_key, str(tenant_id).encode()), KEK_ID

    async def unwrap(self, tenant_id: UUID, wrapped_data_key: bytes, kek_id: str) -> bytes:
        if kek_id != KEK_ID:
            raise ConfigError(f"unknown key-encryption key id {kek_id!r}")
        nonce, ciphertext = wrapped_data_key[:_NONCE_SIZE], wrapped_data_key[_NONCE_SIZE:]
        return self._aead.decrypt(nonce, ciphertext, str(tenant_id).encode())
