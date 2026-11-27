"""Topics and schemas the acquisition pipeline reads and writes (C-03)."""
from __future__ import annotations

from usep.ports.event_bus import SchemaRegistry

RAW_FAMILIES = ("jira", "gitlab", "confluence", "figma", "github", "servicenow", "ado")
RAW_REQUIRED = ("source", "source_type", "source_ref", "source_url", "snapshot_ref", "checksum", "retrieved_at")
QUARANTINE_TOPIC = "quarantine"
ENTITY_REQUIRED = ("kind", "type", "attributes", "evidence_ref", "labels", "idempotency_key")
QUARANTINE_REQUIRED = ("reason_code", "reason", "location", "source_system", "source_ref", "snapshot_ref")


def entity_topic(domain: str) -> str:
    return f"entity.{domain}"


def register_schemas(registry: SchemaRegistry, domains: tuple[str, ...]) -> None:
    for fam in RAW_FAMILIES:
        registry.register(f"raw.{fam}", 1, RAW_REQUIRED)
    for d in domains:
        registry.register(entity_topic(d), 1, ENTITY_REQUIRED)
    registry.register(QUARANTINE_TOPIC, 1, QUARANTINE_REQUIRED)
