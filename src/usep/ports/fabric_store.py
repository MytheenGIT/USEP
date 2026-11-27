"""Fabric store port (C-04). The writer's rules depend on this module and import no database driver.

One `transaction(tenant_id)` is one atomic commit: every call inside it succeeds together or none does. Every method is
scoped to the tenant the transaction was opened for; an adapter must enforce that (PostgreSQL does it with row-level
security as well as in the SQL). Contract: docs/adr/ADR-21-fabric-writer-and-postgres-commit-point.md.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from usep.fabric.model import Assertion, EdgeRecord, EntityState


@dataclass(frozen=True)
class OutboxRow:
    outbox_id: int
    tenant_id: str
    topic: str
    key: str
    type: str
    payload: Mapping[str, Any]
    attempts: int


@dataclass(frozen=True)
class OutboxStatus:
    pending: int
    dead: int
    oldest_pending_seconds: float | None
    last_outbox_id: int


class FabricTx(Protocol):
    def claim(self, idempotency_key: str, outcome: str) -> bool:
        """Record that this key is being applied. False if it already was (a duplicate)."""

    def find_entity(self, source_system: str, source_id: str) -> uuid.UUID | None: ...

    def entity_type(self, entity_id: uuid.UUID) -> str | None: ...

    def create_entity(self, entity_id: uuid.UUID, type: str, domain: str, source_system: str, source_id: str) -> None:
        """Create the entity and bind its source identity."""

    def get_state(self, entity_id: uuid.UUID) -> EntityState | None: ...

    def put_state(self, state: EntityState) -> None: ...

    def add_assertion(self, assertion: Assertion) -> None: ...

    def get_edge(self, edge_key: str) -> EdgeRecord | None: ...

    def put_edge(self, edge: EdgeRecord) -> None: ...

    def link_pending(self, entity_id: uuid.UUID, type: str, source_system: str, source_id: str) -> list[EdgeRecord]:
        """Attach this entity to every pending edge end that names its source identity (and, if the end names a type,
        matches it). Bumps each edge's row_version. Returns the edges changed."""

    def retract(self, source_systems: tuple[str, ...], source_id: str, at: Any) -> tuple[list[EntityState], list[EdgeRecord]]:
        """Mark current state and every edge touching this source identity as retracted. Returns what changed."""

    def reject(self, event_id: str, topic: str, code: str, reason: str) -> None: ...

    def enqueue(self, topic: str, key: str, type: str, payload: Mapping[str, Any]) -> int: ...


class FabricStore(Protocol):
    def transaction(self, tenant_id: str) -> AbstractContextManager[FabricTx]: ...

    def claim_outbox(self, limit: int, max_attempts: int) -> AbstractContextManager[OutboxBatch]:
        """Open a batch of unpublished outbox rows (cross-tenant, id order). Rows the batch marks are committed when the
        context exits; rows it does not mark stay unpublished."""

    def outbox_status(self) -> OutboxStatus: ...


class OutboxBatch(Protocol):
    rows: list[OutboxRow]

    def mark_published(self, outbox_id: int) -> None: ...

    def mark_failed(self, outbox_id: int, error: str) -> None: ...
