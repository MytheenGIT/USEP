"""Domain event value types emitted along the raw-landing path."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RawObjectPublished:
    """The reference-only event published after a raw object is stored. Never
    carries payload bytes."""

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
    # LLD 3.5: every event carries source_version, acl_ref and extracted_at.
    source_version: str | None = None
    extracted_at: datetime | None = None
    # LLD 4.4: until a source permission is mapped to a group, the record is visible to owners only.
    acl_ref: str = "owners-only"
    # Permission attributes harvested from the source (project role, space restrictions, ...), for the mapping step.
    source_acl: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    reason_code: str
    detector_counts: dict[str, int]
