"""Generic HTTP response and exception classification, with no vendor import.

See the target layout, section 4.

The actual `httpx.AsyncClient` call happens in a connector's own adapter (connector phase, out of
scope here); this module only turns a plain status code, header mapping, or a raised exception into
the vendor-neutral vocabulary `usep.ingestion.runtime.retry` understands.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from http import HTTPStatus

from usep.ingestion.runtime.backoff import parse_retry_after

TENANT_HEADER = "X-Tenant-Id"
TRACE_HEADER = "X-Trace-Id"
RETRY_AFTER_HEADER = "Retry-After"
_SUCCESS_STATUSES = range(HTTPStatus.OK, HTTPStatus.BAD_REQUEST)  # 2xx and 3xx
_SERVER_ERROR_STATUSES = range(HTTPStatus.INTERNAL_SERVER_ERROR, HTTPStatus.INTERNAL_SERVER_ERROR + 100)


class Classification(StrEnum):
    """How an HTTP response should be handled."""

    OK = "OK"
    RETRYABLE = "RETRYABLE"
    REJECTED = "REJECTED"


def classify_status(status: int) -> Classification:
    """2xx/3xx: OK. 429 or 5xx: RETRYABLE. Any other 4xx: REJECTED (section 5.7)."""
    if status in _SUCCESS_STATUSES:
        return Classification.OK
    if status == HTTPStatus.TOO_MANY_REQUESTS or status in _SERVER_ERROR_STATUSES:
        return Classification.RETRYABLE
    return Classification.REJECTED


def extract_retry_after_seconds(status: int, headers: Mapping[str, str], *, now: datetime) -> float | None:
    """Return the seconds a 429 response's `Retry-After` header asks to wait.

    Returns `None` if the response is not a 429 or the header is absent or unparseable.
    """
    if status != HTTPStatus.TOO_MANY_REQUESTS:
        return None
    value = headers.get(RETRY_AFTER_HEADER) or headers.get(RETRY_AFTER_HEADER.lower())
    if value is None:
        return None
    return parse_retry_after(value, now=now)


_TRANSIENT_EXCEPTION_TYPE_NAMES = frozenset(
    {
        "TimeoutError",
        "ConnectTimeout",
        "ReadTimeout",
        "ConnectError",
        "ConnectionError",
        "RemoteProtocolError",
    }
)


def is_transient_exception(exc: BaseException) -> bool:
    """Return whether an exception is a timeout or connection-level failure.

    A timeout or connection failure is recognised by stdlib type or generically by exception type
    name, so this module never imports the vendor client whose exception it is classifying.
    """
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    return type(exc).__name__ in _TRANSIENT_EXCEPTION_TYPE_NAMES


def inject_tenant_trace_headers(
    headers: Mapping[str, str], *, tenant_id: str, trace_id: str
) -> dict[str, str]:
    """A copy of `headers` with the tenant and trace propagation headers added."""
    merged = dict(headers)
    merged[TENANT_HEADER] = tenant_id
    merged[TRACE_HEADER] = trace_id
    return merged
