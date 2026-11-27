"""Schemas of the committed-change topics the outbox relay publishes (ADR-21)."""
from __future__ import annotations

from usep.fabric.model import (
    COMMIT_EDGE_REQUIRED,
    COMMIT_EDGE_TOPIC,
    COMMIT_ENTITY_REQUIRED,
    COMMIT_ENTITY_TOPIC,
)
from usep.ports.event_bus import SchemaRegistry


def register_commit_schemas(registry: SchemaRegistry) -> None:
    registry.register(COMMIT_ENTITY_TOPIC, 1, COMMIT_ENTITY_REQUIRED)
    registry.register(COMMIT_EDGE_TOPIC, 1, COMMIT_EDGE_REQUIRED)
