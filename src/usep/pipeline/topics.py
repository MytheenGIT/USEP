"""Topics and schemas the acquisition pipeline reads and writes (C-03)."""
from __future__ import annotations

from usep.ports.event_bus import SchemaRegistry

RAW_FAMILIES = ("jira", "gitlab", "confluence", "figma", "github", "servicenow", "ado")
RAW_REQUIRED = ("source", "source_type", "source_ref", "source_url", "snapshot_ref", "checksum", "retrieved_at")
QUARANTINE_TOPIC = "quarantine"
ENTITY_REQUIRED = ("kind", "type", "attributes", "evidence_ref", "labels", "idempotency_key")
EVIDENCE_SCHEMA_VERSION = 1
# Evidence object (S3 evidence/...): what a chunker or embedder reads. Contract: docs/contracts/evidence.md.
EVIDENCE_OBJECT_FIELDS = (
    "schema_version", "tenant_id", "source_system", "source_object", "source_id", "source_version", "source_url",
    "snapshot_ref", "checksum", "retrieved_at", "title", "text", "labels", "sensitivity", "acl_state", "owners_only",
    "acl", "egress", "redaction", "refs", "ontology")
# Evidence event (topic evidence.<family>): a pointer to one evidence object plus what a consumer needs to decide
# whether and how to read it, without opening it.
EVIDENCE_REQUIRED = ("evidence_ref", "source_system", "source_object", "source_id", "source_version", "snapshot_ref",
                     "checksum", "sensitivity", "acl_state", "owners_only", "acl", "egress", "idempotency_key")
QUARANTINE_REQUIRED = ("reason_code", "reason", "location", "source_system", "source_ref", "snapshot_ref")


def entity_topic(domain: str) -> str:
    return f"entity.{domain}"


def evidence_topic(family: str) -> str:
    return f"evidence.{family}"


def register_schemas(registry: SchemaRegistry, domains: tuple[str, ...]) -> None:
    for fam in RAW_FAMILIES:
        registry.register(f"raw.{fam}", 1, RAW_REQUIRED)
    for fam in RAW_FAMILIES:
        registry.register(evidence_topic(fam), 1, EVIDENCE_REQUIRED)
    for d in domains:
        registry.register(entity_topic(d), 1, ENTITY_REQUIRED)
    registry.register(QUARANTINE_TOPIC, 1, QUARANTINE_REQUIRED)
