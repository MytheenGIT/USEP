from __future__ import annotations

from uuid import UUID, uuid4


class InMemoryKeyEncryption:
    """Fake `KeyEncryptionPort`: XORs the data key with a per-tenant pretend KEK
    (not real cryptography — this is a fake, never imported from production code).
    """

    def __init__(self) -> None:
        self._keks: dict[UUID, bytes] = {}

    def _kek_for(self, tenant_id: UUID) -> bytes:
        if tenant_id not in self._keks:
            self._keks[tenant_id] = uuid4().bytes * 2  # 32 bytes, stable per tenant
        return self._keks[tenant_id]

    async def wrap(self, tenant_id: UUID, data_key: bytes) -> tuple[bytes, str]:
        kek = self._kek_for(tenant_id)
        wrapped = bytes(b ^ kek[i % len(kek)] for i, b in enumerate(data_key))
        return wrapped, f"fake-kek-{tenant_id}"

    async def unwrap(self, tenant_id: UUID, wrapped_data_key: bytes, kek_id: str) -> bytes:
        kek = self._kek_for(tenant_id)
        return bytes(b ^ kek[i % len(kek)] for i, b in enumerate(wrapped_data_key))
