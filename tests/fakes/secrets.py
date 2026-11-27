from __future__ import annotations

from usep.ingestion.ports.secrets import SecretValue


class InMemorySecretResolver:
    """Fake `SecretResolverPort`. Never imported from production code."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}

    async def resolve(self, ref: str) -> SecretValue:
        return SecretValue(self._values[ref])
