"""UUID v7 generation (ground rule, section 1: every generated ID is UUID v7).

Uses the `uuid6` package rather than the stdlib (Python's `uuid` module gains
`uuid7()` only in 3.14+; this project targets 3.12, and the ground rules name
`uuid6` explicitly).

The pipeline and the event bus use `uuid7()` below (monotonic inside one process, so S3 listing order is creation order),
plus `utc_now_iso()` and `to_iso()`. `new_id()` is the ingestion package's generator.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone

from uuid6 import uuid7 as _uuid6_v7


def new_id() -> uuid.UUID:
    """A fresh, time-ordered UUID v7. Use this for every generated ID in the system."""
    return _uuid6_v7()


_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> uuid.UUID:
    """RFC 9562 UUID v7. Monotonic inside one process: ids sort in creation order, even in one millisecond.

    S3 lists keys in lexical order, so the event bus relies on this for per-key ordering.
    """
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms <= _last_ms:
            ms = _last_ms
            _counter += 1
            if _counter > 0xFFF:          # counter space spent: move to the next millisecond
                ms += 1
                _counter = 0
        else:
            _counter = int.from_bytes(os.urandom(2), "big") & 0x3FF   # leave headroom to count up
        _last_ms = ms
        rand_a, rand_b = _counter, int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | rand_a << 64 | 0b10 << 62 | rand_b
    return uuid.UUID(int=value)


def utc_now_iso() -> str:
    return to_iso(datetime.now(timezone.utc))


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetime: timestamps must be UTC")
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
