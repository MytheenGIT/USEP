"""Canonical labelled record (one normalised record after classification, enrichment and validation).

Field names follow ontology/core/common-attributes.yml; nothing here duplicates a field under another name.
`concept` is always the canonical core or pack concept. Labels never replace it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# processing_status values
LABELLED, QUARANTINED, EVIDENCE, CARRIER, UNMODELLED, RELATIONSHIP = (
    "labelled", "quarantined", "evidence", "carrier", "unmodelled", "relationship")

# quarantine reason codes
Q_UNMAPPED_TYPE = "Q-UNMAPPED-TYPE"
Q_SCHEMA = "Q-SCHEMA"
Q_AMBIGUOUS = "Q-AMBIGUOUS"
Q_TENANT = "Q-TENANT"
Q_LOW_CONFIDENCE = "Q-LOW-CONFIDENCE"      # reserved for LLM-assisted labelling (not built)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    code: str            # e.g. required_missing, vocab_value, temporal, type
    field: str
    message: str
    severity: str = "error"


@dataclass(frozen=True, slots=True)
class Label:
    value: str            # display label, e.g. "Squad"
    level: str            # core | industry | organization | application | project
    kind: str             # concept | domain | alias | custom
    source: str           # pack id or label-definition id that supplied it
    reason: str


@dataclass(slots=True)
class FieldProvenance:
    value: Any
    layer: str            # which level supplied the winning value
    source: str           # mapping source path, definition id or "default"
    reason: str
    contributions: list[dict[str, Any]] = field(default_factory=list)   # every candidate, winner included


@dataclass(slots=True)
class LabelledRecord:
    tenant_id: str
    entity_id: str | None
    concept: str | None
    ontology_level: str | None            # level that defined `concept`
    ontology_pack_id: str | None
    ontology_pack_version: str | None
    ontology_version: str                 # core version
    domain: str | None
    source_system: str
    source_type: str
    source_id: str | None
    source_version: str | None = None
    source_uri: str | None = None
    name: str | None = None
    summary: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    custom_labels: list[Label] = field(default_factory=list)
    sensitivity: int | None = None
    owner_ref: str | None = None
    acl_ref: str | None = None
    acl_state: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    recorded_at: str | None = None
    confidence: float = 1.0
    evidence_ref: str | None = None
    mapping_rule_id: str | None = None
    mapping_rule_version: str | None = None
    processing_status: str = LABELLED
    reason_code: str | None = None
    validation_results: list[ValidationResult] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)
    field_provenance: dict[str, FieldProvenance] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.processing_status == LABELLED
