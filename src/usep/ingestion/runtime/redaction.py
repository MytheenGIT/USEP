"""Redact credential-bearing headers and bearer tokens before anything is logged
(section 5.7, 8; ground rule, section 1: no secret value in logs)."""

from __future__ import annotations

import re
from collections.abc import Mapping

REDACTED_HEADER_NAMES = frozenset(
    {
        "authorization",
        "private-token",
        "cookie",
        "set-cookie",
        "job-token",
        "x-api-key",
        "proxy-authorization",
    }
)

_REDACTED = "<redacted>"
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-_.=]{8,}")


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """A copy of `headers` with every credential-bearing header's value replaced."""
    return {
        name: (_REDACTED if name.lower() in REDACTED_HEADER_NAMES else value)
        for name, value in headers.items()
    }


def redact_text(text: str) -> str:
    """Redact a bearer token appearing anywhere in free text (for example an
    exception message that happened to echo a header)."""
    return _BEARER_RE.sub(f"Bearer {_REDACTED}", text)
