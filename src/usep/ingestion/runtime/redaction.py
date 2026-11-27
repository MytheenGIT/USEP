"""Redact credential-bearing headers and bearer tokens before anything is logged.

Ground rule, section 1: no secret value in logs (also sections 5.7 and 8).
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from usep.ingestion.ports.secrets import REDACTED

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

_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-_.=]{8,}")


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """A copy of `headers` with every credential-bearing header's value replaced."""
    return {
        name: (REDACTED if name.lower() in REDACTED_HEADER_NAMES else value)
        for name, value in headers.items()
    }


def redact_text(text: str) -> str:
    """Redact a bearer token anywhere in free text.

    For example, an exception message that happened to echo a header.
    """
    return _BEARER_RE.sub(f"Bearer {REDACTED}", text)
