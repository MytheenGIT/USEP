from __future__ import annotations

import datetime as dt

from usep.ingestion.runtime.http import (
    Classification,
    classify_status,
    extract_retry_after_seconds,
    inject_tenant_trace_headers,
    is_transient_exception,
)


def test_classify_status() -> None:
    assert classify_status(200) is Classification.OK
    assert classify_status(304) is Classification.OK
    assert classify_status(429) is Classification.RETRYABLE
    assert classify_status(500) is Classification.RETRYABLE
    assert classify_status(503) is Classification.RETRYABLE
    assert classify_status(404) is Classification.REJECTED
    assert classify_status(403) is Classification.REJECTED


def test_extract_retry_after_seconds_only_for_429() -> None:
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    assert extract_retry_after_seconds(500, {"Retry-After": "10"}, now=now) is None
    assert extract_retry_after_seconds(429, {}, now=now) is None
    assert extract_retry_after_seconds(429, {"Retry-After": "10"}, now=now) == 10.0


def test_is_transient_exception() -> None:
    assert is_transient_exception(TimeoutError())
    assert is_transient_exception(ConnectionError())

    class ReadTimeout(Exception):  # noqa: N818 - mirrors the httpx name the classifier matches
        pass

    assert is_transient_exception(ReadTimeout())
    assert not is_transient_exception(ValueError("not transient"))


def test_inject_tenant_trace_headers_does_not_mutate_input() -> None:
    original = {"Accept": "application/json"}
    merged = inject_tenant_trace_headers(original, tenant_id="t-1", trace_id="tr-1")
    assert original == {"Accept": "application/json"}
    assert merged["X-Tenant-Id"] == "t-1"
    assert merged["X-Trace-Id"] == "tr-1"
    assert merged["Accept"] == "application/json"
