"""Domain event value types emitted along the raw-landing path."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RawObjectPublished:
    """The reference-only event published after a raw object is stored.

    Never carries payload bytes.
    """

    event_id: UUID
    schema_version: str
    tenant_id: UUID
    source: str
    scope_id: str
    object_type: str
    object_id: str
    object_key: str
    content_hash: str
    run_id: UUID
    checkpoint: str | None


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """What is kept for a quarantined object: reason and match counts, never the text."""

    reason_code: str
    detector_counts: dict[str, int]
