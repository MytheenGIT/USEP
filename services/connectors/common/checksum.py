"""Canonical bytes and checksum of a raw payload, so the same payload always has the same snapshot key."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def payload_checksum(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()
