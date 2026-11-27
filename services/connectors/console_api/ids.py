from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime


def uuid7() -> str:
    """UUID v7 (RFC 9562): 48-bit unix ms timestamp, then random bits."""
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms << 80) | (0x7 << 76) | (((rand >> 62) & 0xFFF) << 64) | (0b10 << 62) | (rand & ((1 << 62) - 1))
    return str(uuid.UUID(int=value))


def utc_now_iso() -> str:
    """UTC ISO 8601 with milliseconds, e.g. 2026-11-25T09:14:03.120Z."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
