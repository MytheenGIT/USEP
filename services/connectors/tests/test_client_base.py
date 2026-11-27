from __future__ import annotations

import httpx
import pytest

from common.client_base import BaseAPIClient, retry_after_seconds


class Slept(list):
    async def __call__(self, seconds: float) -> None:
        self.append(seconds)


def client(handler, retries=3, sleeps=None):
    return BaseAPIClient("https://x.test", transport=httpx.MockTransport(handler), retries=retries,
                         backoff_seconds=1.0, sleep=sleeps if sleeps is not None else Slept())


@pytest.mark.asyncio
async def test_rate_limit_is_retried_honouring_retry_after_then_succeeds():
    calls, sleeps = [], Slept()

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "7"}) if len(calls) < 3 else httpx.Response(200, json={"ok": 1})

    assert await client(handler, sleeps=sleeps).get_json("/a") == {"ok": 1}
    assert len(calls) == 3 and sleeps == [7.0, 7.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [502, 503, 504])
async def test_availability_errors_are_retried_with_exponential_backoff(status):
    calls, sleeps = [], Slept()

    def handler(request):
        calls.append(1)
        return httpx.Response(status) if len(calls) < 3 else httpx.Response(200, json=[])

    await client(handler, sleeps=sleeps).get_json("/a")
    assert len(calls) == 3 and 0.5 <= sleeps[0] <= 1.0 and 1.0 <= sleeps[1] <= 2.0        # 1s then 2s, jittered


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 500])
async def test_other_errors_are_not_retried(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status)

    with pytest.raises(httpx.HTTPStatusError):
        await client(handler).get_json("/a")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_retries_are_bounded_and_the_last_error_is_raised():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(httpx.HTTPStatusError) as e:
        await client(handler, retries=2).get_json("/a")
    assert len(calls) == 3 and e.value.response.status_code == 503


@pytest.mark.asyncio
async def test_transport_errors_are_retried():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"ok": True})

    assert await client(handler).get_json("/a") == {"ok": True} and len(calls) == 2


@pytest.mark.asyncio
async def test_post_reads_are_retried_too_and_retries_zero_means_none():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={"v": 1})

    assert await client(handler).post_json("/q", json={"a": 1}) == {"v": 1} and len(calls) == 2
    calls.clear()
    with pytest.raises(httpx.HTTPStatusError):
        await client(lambda r: (calls.append(1), httpx.Response(503))[1], retries=0).get_json("/a")
    assert len(calls) == 1


def test_retry_after_parsing():
    assert retry_after_seconds(httpx.Response(429, headers={"Retry-After": "3"})) == 3.0
    assert retry_after_seconds(httpx.Response(429)) is None
    assert retry_after_seconds(httpx.Response(429, headers={"Retry-After": "garbage"})) is None
    assert retry_after_seconds(httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})) == 0.0
