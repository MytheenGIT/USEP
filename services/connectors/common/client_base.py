"""Shared async HTTP client base for all source clients.

Retries, back-off and rate limiting belong to the connector runtime and are
not implemented here; this stays a thin transport wrapper.
"""

from __future__ import annotations

from typing import Any

import httpx


class PayloadTooLarge(Exception):
    def __init__(self, size: int, limit: int) -> None:
        super().__init__(f"payload of {size} bytes exceeds limit of {limit} bytes")
        self.size = size
        self.limit = limit


class BaseAPIClient:
    """Thin async wrapper around httpx with shared error handling.

    Kept vendor-agnostic on purpose: subclasses only know their source's
    endpoints and pagination shape, not transport concerns. ``transport`` is
    only for tests (``httpx.MockTransport``).
    """

    def __init__(
        self,
        base_url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        auth: httpx.Auth | tuple[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url, headers=headers or {}, timeout=timeout, auth=auth, transport=transport
        )

    async def get_response(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return (await self.get_response(path, params=params)).json()

    async def post_json(self, path: str, json: dict[str, Any] | None = None) -> Any:
        response = await self._client.post(path, json=json)
        response.raise_for_status()
        return response.json()

    async def get_bytes(self, url: str, max_bytes: int) -> bytes:
        """Download from this source's own host with its credentials, following redirects.

        httpx drops the Authorization header on cross-origin redirects, so a
        redirect to a media host does not receive the credentials.
        """
        return await _download(self._client, url, max_bytes)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "BaseAPIClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


async def download_unauthenticated(url: str, max_bytes: int, timeout: float = 60.0) -> bytes:
    """Download a presigned or public URL without any source credentials."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await _download(client, url, max_bytes)


async def _download(client: httpx.AsyncClient, url: str, max_bytes: int) -> bytes:
    async with client.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()
        declared = int(response.headers.get("content-length") or 0)
        if declared > max_bytes:
            raise PayloadTooLarge(declared, max_bytes)
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise PayloadTooLarge(total, max_bytes)
            chunks.append(chunk)
        return b"".join(chunks)
