"""`RawObjectRef` and the canonical-JSON hashing and key scheme."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


def canonicalize(payload: Any) -> bytes:
    """Sorted keys, UTF-8, no insignificant whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_hash(canonical_bytes: bytes) -> str:
    return hashlib.sha256(canonical_bytes).hexdigest()


def object_key(
    tenant_id: UUID,
    source: str,
    scope_id: str,
    object_type: str,
    object_id: str,
    content_hash_hex: str,
) -> str:
    """`raw/{tenant_id}/{source}/{scope_id}/{object_type}/{object_id}/{content_hash}.json`.

    No `run_id` in the key — the same object fetched again in a later run resolves
    to the same prefix; only a changed content hash produces a new, distinct key,
    so the old object is kept rather than silently overwritten, and "skip if
    unchanged" dedupes across runs.
    """
    return f"raw/{tenant_id}/{source}/{scope_id}/{object_type}/{object_id}/{content_hash_hex}.json"


@dataclass(frozen=True, slots=True)
class RawObjectRef:
    tenant_id: UUID
    source: str
    object_type: str
    object_id: str
    content_hash: str
    scope_id: str
    object_key: str
    byte_size: int
    run_id: UUID
    imported_at: datetime
    published_at: datetime | None
    wrapped_dek: bytes | None
    kek_id: str
    tombstoned_at: datetime | None = None
    first_seen_extra_at: datetime | None = None
