"""Fabric domain types: what the writer reads from the bus and what it commits. No vendor SDK."""
from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

COMMIT_ENTITY_TOPIC = "commit.entity"
COMMIT_EDGE_TOPIC = "commit.edge"
# Required payload fields of the committed-change events (ADR-21). `change` is committed | retracted.
COMMIT_ENTITY_REQUIRED = ("entity_id", "type", "row_version", "change", "idempotency_key")
COMMIT_EDGE_REQUIRED = ("edge_id", "type", "row_version", "change", "idempotency_key")

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class RejectedEvent(Exception):
    """The event cannot be committed. `code` is a stable reason code; it is stored, never the event content."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def parse_ts(value: Any, default: datetime | None = None) -> datetime:
    """UTC ISO 8601 (a trailing Z is accepted) to an aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        if default is not None:
            return default
        raise RejectedEvent("bad_timestamp", "missing timestamp")
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RejectedEvent("bad_timestamp", f"not an ISO 8601 timestamp: {value!r}") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def edge_key(tenant_id: str, rel: str, from_ref: Mapping[str, Any], to_ref: Mapping[str, Any]) -> str:
    return hashlib.sha256("|".join([tenant_id, rel, ref_identity(from_ref), ref_identity(to_ref)]).encode()).hexdigest()


def ref_identity(ref: Mapping[str, Any]) -> str:
    """`system:id` of an edge end. A repository reference stands in for the id when the end names a repo."""
    return f"{ref.get('source_system', '')}:{ref.get('source_id') or ref.get('repository_ref') or ''}"


@dataclass(frozen=True)
class NodeCandidate:
    tenant_id: str
    domain: str
    type: str
    source_system: str
    source_id: str
    source_version: str
    valid_from: datetime
    attributes: Mapping[str, Any]
    labels: Mapping[str, Any]
    evidence_ref: str
    snapshot_ref: str
    ontology: str
    idempotency_key: str


@dataclass(frozen=True)
class EdgeCandidate:
    tenant_id: str
    domain: str
    type: str
    from_ref: Mapping[str, Any]
    to_ref: Mapping[str, Any]
    attributes: Mapping[str, Any]
    labels: Mapping[str, Any]
    evidence_ref: str
    snapshot_ref: str
    ontology: str
    idempotency_key: str


@dataclass(frozen=True)
class Retraction:
    tenant_id: str
    source_systems: tuple[str, ...]
    source_id: str
    scope: str
    reason: str
    detected_at: datetime
    idempotency_key: str


@dataclass(frozen=True)
class EntityState:
    entity_id: uuid.UUID
    type: str
    domain: str
    attributes: Mapping[str, Any]
    labels: Mapping[str, Any]
    source_version: str
    valid_from: datetime
    evidence_ref: str
    snapshot_ref: str
    ontology: str
    row_version: int
    retracted_at: datetime | None = None

    @property
    def retracted(self) -> bool:
        return self.retracted_at is not None

    def with_(self, **kw: Any) -> EntityState:
        return replace(self, **kw)


@dataclass(frozen=True)
class EdgeRecord:
    edge_id: uuid.UUID
    edge_key: str
    type: str
    domain: str
    from_ref: Mapping[str, Any]
    to_ref: Mapping[str, Any]
    from_entity_id: uuid.UUID | None
    to_entity_id: uuid.UUID | None
    attributes: Mapping[str, Any]
    labels: Mapping[str, Any]
    evidence_ref: str
    snapshot_ref: str
    ontology: str
    row_version: int
    retracted: bool = False

    @property
    def pending(self) -> bool:
        return self.from_entity_id is None or self.to_entity_id is None

    def with_(self, **kw: Any) -> EdgeRecord:
        return replace(self, **kw)


@dataclass(frozen=True)
class Assertion:
    assertion_id: uuid.UUID
    subject_kind: str                 # node | edge | retraction
    subject_id: uuid.UUID | None
    type: str
    attributes: Mapping[str, Any]
    labels: Mapping[str, Any]
    evidence_ref: str
    snapshot_ref: str
    source_version: str
    valid_from: datetime | None
    ontology: str
    idempotency_key: str
    applied: bool
    reason: str = ""


@dataclass(frozen=True)
class Applied:
    """Result of handling one event. status: committed | stale | duplicate | rejected | retracted."""

    status: str
    entity_id: uuid.UUID | None = None
    edge_id: uuid.UUID | None = None
    detail: str = ""
    outbox: int = 0
    extra: Mapping[str, Any] = field(default_factory=dict)
