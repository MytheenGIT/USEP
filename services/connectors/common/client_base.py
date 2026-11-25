"""Shared async HTTP client base for all source clients."""

from __future__ import annotations

from typing import Any

import httpx


class BaseAPIClient:
    """Thin async wrapper around httpx with shared error handling.

    Kept vendor-agnostic on purpose: subclasses only know their source's
    endpoints and pagination shape, not transport concerns.
    """

    def __init__(self, base_url: str, headers: dict[str, str] | None = None, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, headers=headers or {}, timeout=timeout)

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def post_json(self, path: str, json: dict[str, Any] | None = None) -> Any:
        response = await self._client.post(path, json=json)
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "BaseAPIClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
