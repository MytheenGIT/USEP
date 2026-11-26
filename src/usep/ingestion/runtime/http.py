"""Generic HTTP response/exception classification — no vendor import here (target
layout, section 4). The actual `httpx.AsyncClient` call happens in a connector's own
adapter (connector phase, out of scope here); this module only turns a plain status
code, header mapping, or a raised exception into the vendor-neutral vocabulary
`usep.ingestion.runtime.retry` understands.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum

from usep.ingestion.runtime.backoff import parse_retry_after


class Classification(StrEnum):
    OK = "OK"
    RETRYABLE = "RETRYABLE"
    REJECTED = "REJECTED"


def classify_status(status: int) -> Classification:
    """2xx/3xx: OK. 429 or 5xx: RETRYABLE. Any other 4xx: REJECTED (section 5.7)."""
    if 200 <= status < 400:
        return Classification.OK
    if status == 429 or 500 <= status < 600:
        return Classification.RETRYABLE
    return Classification.REJECTED


def extract_retry_after_seconds(status: int, headers: Mapping[str, str], *, now: datetime) -> float | None:
    """Seconds to wait per a 429 response's `Retry-After` header; `None` if the
    response isn't a 429 or the header is absent/unparseable."""
    if status != 429:
        return None
    value = headers.get("Retry-After") or headers.get("retry-after")
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
    """True for a timeout or connection-level failure, recognised generically by
    exception type name (so this module never imports the vendor client whose
    exception it is classifying) or by stdlib type."""
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    return type(exc).__name__ in _TRANSIENT_EXCEPTION_TYPE_NAMES


def inject_tenant_trace_headers(
    headers: Mapping[str, str], *, tenant_id: str, trace_id: str
) -> dict[str, str]:
    """A copy of `headers` with the tenant and trace propagation headers added."""
    merged = dict(headers)
    merged["X-Tenant-Id"] = tenant_id
    merged["X-Trace-Id"] = trace_id
    return merged
