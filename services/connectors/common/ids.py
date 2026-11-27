"""UUID v7 (RFC 9562), monotonic inside one process. S3 lists keys in lexical order, so event ids sort in creation
order. Same algorithm as usep.core.ids: the connectors image does not import the usep package."""
from __future__ import annotations

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> uuid.UUID:
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms <= _last_ms:
            ms = _last_ms
            _counter += 1
            if _counter > 0xFFF:
                ms, _counter = ms + 1, 0
        else:
            _counter = int.from_bytes(os.urandom(2), "big") & 0x3FF
        _last_ms = ms
        rand_a, rand_b = _counter, int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    return uuid.UUID(int=(ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | rand_a << 64 | 0b10 << 62 | rand_b)
