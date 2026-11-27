"""`SpiffeSvidProvider`: `SvidProviderPort` over a SPIFFE Workload API client (D4).

The client (for example a `spiffe` library workload client wrapped to be awaitable) is injected, so this module imports no
vendor SDK and tests pass a fake. Pending security-architect ratification (ADR-22, Proposed).
"""

from __future__ import annotations

from typing import Protocol


class WorkloadClient(Protocol):
    async def fetch_jwt_svid(self, audience: str) -> str: ...


class SpiffeSvidProvider:
    def __init__(self, client: WorkloadClient) -> None:
        self._client = client

    async def fetch_jwt_svid(self, audience: str) -> str:
        return await self._client.fetch_jwt_svid(audience)
