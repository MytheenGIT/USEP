"""Shared domain value types used across package boundaries.

`SourceRecord` is depended on today by the existing `usep.ontology.gate` module
(`gate.py` reads `.attributes`, `.entity_type` and `.source_system` and nothing
else — verified by reading that file; see docs/plans/ASSUMPTIONS.md). Its shape
here is deliberately exactly that surface, no more: this package does not own the
richer, ingestion-specific record types (raw objects, cursors, ...), which live in
`usep.ingestion.domain` instead.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

TenantId = UUID
"""Every record, token, cursor, rate-limit key, object key and query carries one
of these (ground rule, section 1). A plain alias, not a NewType, so it composes
freely with pydantic models and ordinary UUID equality/hashing."""


class SourceRecord(BaseModel):
    """One record as read from a source system, before ontology mapping.

    Consumed today by `usep.ontology.gate.OntologyGate.check()`, which reads
    `attributes`, `entity_type` and `source_system` only.
    """

    model_config = ConfigDict(frozen=True)

    source_system: str
    entity_type: str | None = None
    attributes: dict[str, Any] = {}
