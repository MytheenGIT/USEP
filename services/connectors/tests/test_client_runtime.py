from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from common.client_base import BaseAPIClient, ClientRuntime
from usep.core.clock import SystemClock
from usep.ingestion.runtime.observer import DeadLetterEvent, ListObserver, RetryEvent
from usep.ingestion.runtime.rate_limiter import RateLimiter, RateLimitKey
from usep.ingestion.runtime.retry import RetryPolicy

TENANT = uuid4()


def _client(handler, observer: ListObserver | None = None, attempts: int = 3) -> BaseAPIClient:
    clock = SystemClock()
    limiter = RateLimiter(clock, backfill_fraction=0.5)
    limiter.configure(TENANT, "jira", "acct", rate_per_second=1000.0)
    runtime = ClientRuntime(
        source_system="jira",
        key=RateLimitKey(TENANT, "jira", "acct", "live"),
        policy=RetryPolicy(max_attempts=attempts, base_delay_s=0.001, max_delay_s=0.01),
        rate_limiter=limiter,
        clock=clock,
        observer=observer or ListObserver(),
    )
    return BaseAPIClient("https://example.test", transport=httpx.MockTransport(handler), runtime=runtime)


async def test_429_with_retry_after_is_waited_out_then_succeeds() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    assert await _client(handler).get_json("/x") == {"ok": True}
    assert len(calls) == 2


async def test_5xx_is_retried_with_backoff() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"n": 3})

    observer = ListObserver()
    assert await _client(handler, observer).get_json("/x") == {"n": 3}
    assert len(calls) == 3 and len([e for e in observer.events if isinstance(e, RetryEvent)]) == 2


async def test_4xx_is_not_retried_and_keeps_the_status() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    with pytest.raises(httpx.HTTPStatusError) as caught:
        await _client(handler).get_json("/missing")
    assert caught.value.response.status_code == 404 and len(calls) == 1


async def test_gives_up_after_the_last_attempt_and_raises_the_status() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500)

    observer = ListObserver()
    with pytest.raises(httpx.HTTPStatusError) as caught:
        await _client(handler, observer, attempts=3).get_json("/x")
    assert caught.value.response.status_code == 500 and len(calls) == 3 and len([e for e in observer.events if isinstance(e, DeadLetterEvent)]) == 1


@pytest.mark.parametrize("error", [httpx.ReadError, httpx.WriteError, httpx.WriteTimeout, httpx.PoolTimeout, httpx.ProxyError])
async def test_every_transport_error_is_retried(error) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise error("connection dropped")
        return httpx.Response(200, json={"ok": 1})

    assert await _client(handler).get_json("/x") == {"ok": 1}
    assert len(calls) == 2


async def test_connection_errors_are_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"ok": 1})

    assert await _client(handler).get_json("/x") == {"ok": 1}


async def test_a_malformed_url_is_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.UnsupportedProtocol("Request URL is missing an 'http://' or 'https://' protocol.")

    with pytest.raises(httpx.UnsupportedProtocol):
        await _client(handler).get_json("/x")
    assert len(calls) == 1


def test_trusting_the_system_store_does_not_break_boto3() -> None:
    """truststore.inject_into_ssl() patches ssl process-wide and makes botocore recurse until it crashes."""
    from botocore.httpsession import URLLib3Session

    from common.client_base import system_trust

    system_trust()
    assert URLLib3Session()._get_ssl_context() is not None
    import ssl

    assert ssl.SSLContext.__module__ == "ssl"  # nothing replaced it
