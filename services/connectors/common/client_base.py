"""Shared async HTTP client base for all source clients.

A thin transport wrapper with one addition: reads that fail with a rate limit (429), a gateway or availability error
(502, 503, 504) or a transport error are retried with back-off, honouring ``Retry-After``. Every request any client sends
is a read (the POSTs are ADO's WIQL and batch lookups), so a retry is safe. Anything else (400, 401, 403, 404, 500)
raises at once. Retries are bounded: after ``retries`` extra attempts the last error is raised and the sync reports it.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from datetime import UTC, datetime
from typing import Any

import httpx

RETRY_STATUS = frozenset({429, 502, 503, 504})
MAX_BACKOFF_SECONDS = 60.0


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds named by a Retry-After header (delta-seconds or an HTTP date), or None."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        return max(0.0, (when - datetime.now(UTC)).total_seconds())


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
        retries: int = 3,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url, headers=headers or {}, timeout=timeout, auth=auth, transport=transport
        )
        self._retries, self._backoff, self._sleep = max(0, retries), backoff_seconds, sleep

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        hinted = retry_after_seconds(response) if response is not None else None
        if hinted is not None:
            return min(hinted, MAX_BACKOFF_SECONDS)
        return min(self._backoff * (2**attempt), MAX_BACKOFF_SECONDS) * (0.5 + random.random() / 2)   # jitter

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """One request with bounded retries. Returns a response whose status has been checked."""
        for attempt in range(self._retries + 1):
            try:
                response = await self._client.request(method, path, **kwargs)
            except (httpx.TransportError, httpx.TimeoutException):
                if attempt == self._retries:
                    raise
                await self._sleep(self._delay(attempt, None))
                continue
            if response.status_code in RETRY_STATUS and attempt < self._retries:
                await self._sleep(self._delay(attempt, response))
                continue
            response.raise_for_status()
            return response
        raise AssertionError("unreachable")                      # the loop always returns or raises

    async def get_response(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        return await self._send("GET", path, params=params)

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return (await self.get_response(path, params=params)).json()

    async def post_json(self, path: str, json: dict[str, Any] | None = None) -> Any:
        return (await self._send("POST", path, json=json)).json()

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
