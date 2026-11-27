"""Shared async HTTP client base for all source clients.

Every request goes through the foundation's connector runtime when a ``ClientRuntime`` is
given: a rate-limit token first, then the call, then retry with full-jitter back-off on 429
and 5xx, honouring ``Retry-After`` (LLD 4.3). Without a runtime the client is a plain
httpx wrapper, which is what the unit tests use.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from typing import Any

import httpx
import truststore

from usep.core.clock import Clock
from usep.core.errors import TransientError
from usep.ingestion.runtime.http import Classification, classify_status, extract_retry_after_seconds, is_transient_exception
from usep.ingestion.runtime.observer import Observer
from usep.ingestion.runtime.rate_limiter import RateLimiter, RateLimitKey
from usep.ingestion.runtime.retry import Outcome, RetryPolicy, SendOutcome, call_with_retry


_system_trust: ssl.SSLContext | None = None


def system_trust() -> ssl.SSLContext:
    """TLS trust from the operating system, for calls to the sources (a corporate proxy's certificate is trusted there).

    Used only for these httpx clients. ``truststore.inject_into_ssl()`` would patch ssl for the whole process and
    makes botocore, so the S3 adapter, fail with a RecursionError.
    """
    global _system_trust
    if _system_trust is None:
        _system_trust = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return _system_trust


@dataclass(frozen=True)
class ClientRuntime:
    """Everything one source's client needs to call out politely."""

    source_system: str
    key: RateLimitKey
    policy: RetryPolicy
    rate_limiter: RateLimiter
    clock: Clock
    observer: Observer


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
        runtime: ClientRuntime | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url, headers=headers or {}, timeout=timeout, auth=auth, transport=transport, verify=system_trust()
        )
        self._runtime = runtime

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """One call, with rate limiting and retries when a runtime is set.

        Raises ``httpx.HTTPStatusError`` for a final non-2xx answer (so callers can still look at
        the status), or the last transport error if the source never answered.
        """
        runtime = self._runtime
        if runtime is None:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
            return response

        last_response: httpx.Response | None = None
        last_error: BaseException | None = None

        async def send() -> SendOutcome[httpx.Response]:
            nonlocal last_response, last_error
            try:
                response = await self._client.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                last_error = exc
                # A transport error is worth retrying, except a malformed URL, which will never work.
                if (isinstance(exc, httpx.TransportError) and not isinstance(exc, httpx.UnsupportedProtocol)) or is_transient_exception(exc):
                    raise TransientError(type(exc).__name__) from exc
                raise
            last_response, last_error = response, None
            status = response.status_code
            classification = classify_status(status)
            if classification is Classification.OK:
                return SendOutcome(classification, value=response)
            return SendOutcome(
                classification,
                is_429=status == 429,
                retry_after_s=extract_retry_after_seconds(status, response.headers, now=runtime.clock.now()),
                reason=f"HTTP {status}",
            )

        result = await call_with_retry(
            send,
            key=runtime.key,
            policy=runtime.policy,
            rate_limiter=runtime.rate_limiter,
            clock=runtime.clock,
            observer=runtime.observer,
            endpoint=path,
            source_system=runtime.source_system,
        )
        if result.outcome is Outcome.OK and result.value is not None:
            return result.value
        if last_response is not None and last_error is None:
            last_response.raise_for_status()  # 4xx, or 429/5xx after the last attempt
        raise last_error or RuntimeError(f"{runtime.source_system} call failed: {result.reason}")

    async def get_response(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        return await self._request("GET", path, params=params)

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return (await self.get_response(path, params=params)).json()

    async def post_json(self, path: str, json: dict[str, Any] | None = None) -> Any:
        return (await self._request("POST", path, json=json)).json()

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


def error_detail(exc: BaseException) -> str:
    """A short, safe reason for a failed call: the HTTP status and the source's own message, never a body dump."""
    if isinstance(exc, httpx.HTTPStatusError):
        text = f"HTTP {exc.response.status_code}"
        try:
            body = exc.response.json()
        except ValueError:
            return text
        message = None
        if isinstance(body, dict):
            errors = body.get("errorMessages")
            message = (errors[0] if errors else None) or body.get("message") or body.get("error")
        return f"{text}: {str(message)[:200]}" if message else text
    return type(exc).__name__


async def download_unauthenticated(url: str, max_bytes: int, timeout: float = 60.0) -> bytes:
    """Download a presigned or public URL without any source credentials."""
    async with httpx.AsyncClient(timeout=timeout, verify=system_trust()) as client:
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
