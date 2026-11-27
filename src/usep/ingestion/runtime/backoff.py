"""Full-jitter exponential back-off and `Retry-After` header parsing (LLD §4.3; D7)."""

from __future__ import annotations

import email.utils
import random
from datetime import UTC, datetime


def compute_delay(
    attempt: int,
    base_delay_s: float,
    max_delay_s: float,
    *,
    rng: random.Random | None = None,
) -> float:
    """Return a full-jitter back-off delay for a 1-based retry `attempt`.

    The delay is uniform(0, min(max_delay_s, base * 2**(attempt-1))).

    Matches section 5.7 exactly: base 2s, doubling, capped at `max_delay_s` (600s).
    """
    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    ceiling = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
    source = rng if rng is not None else random
    return source.uniform(0, ceiling)


def parse_retry_after(value: str, *, now: datetime) -> float | None:
    """Parse a `Retry-After` header value (delay-seconds or an HTTP-date) to seconds from `now`.

    Returns `None` if the value cannot be parsed either way.
    """
    text = value.strip()
    if not text:
        return None
    if text.isascii() and text.isdigit():  # str.isdigit() is also true for "²", which float() rejects
        return float(text)
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max((parsed - now).total_seconds(), 0.0)
