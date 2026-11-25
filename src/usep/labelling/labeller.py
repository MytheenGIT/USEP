"""Deterministic labelling of one source record against the pinned ontology (dry-run by default).

Stages, kept separate: (1) extraction of source fields, (2) classification by the application-pack mapping,
(3) label assignment (domain, organisation glossary, custom definitions), (4) metadata enrichment (defaults),
(5) vocabulary normalisation, (6) constraint validation. Persistence and graph projection are not done here:
the result is a value, so it is safe to preview. Nothing is guessed: no mapping means quarantine (or evidence
when the mapping file says so). An LLM classifier is not built; `Q-LOW-CONFIDENCE` is reserved for it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from usep.labelling.definitions import LabelDefinition
from usep.labelling.model import (CARRIER, EVIDENCE, LABELLED, Q_AMBIGUOUS, Q_SCHEMA, Q_TENANT, Q_UNMAPPED_TYPE,
                                  QUARANTINED, RELATIONSHIP, UNMODELLED, FieldProvenance, Label, LabelledRecord,
                                  ValidationResult)
from usep.labelling.resolver import effective_properties
from usep.labelling.resolver_types import PropertyDef, check_value
from usep.ontology.bundle import MappingEntry
from usep.ontology.view import LEVELS, OntologyView

_COMMON = ("name", "summary", "source_id", "source_version", "owner_ref", "acl_ref", "acl_state", "sensitivity",
           "valid_from", "valid_to", "source_uri")
_ENTITY_NS = uuid.UUID("6f1b6a42-2d0e-4a39-9a4e-0e2c4b8f5d11")   # fixed namespace for derived entity ids
_CARRIER_STATUS = {"carrier": CARRIER, "unmodelled": UNMODELLED, "evidence": EVIDENCE}


def derive_entity_id(tenant_id: str, concept: str, source_system: str, source_id: str) -> str:
    """Deterministic id from the natural key so re-labelling the same record is idempotent.
    Open decision: ADR convention says UUID v7 (not reproducible); identity resolution belongs to the fabric writer."""
    return str(uuid.uuid5(_ENTITY_NS, f"{tenant_id}|{concept}|{source_system}|{source_id}"))


def _lookup(payload: Mapping[str, Any], path: str, source_object: str) -> Any:
    """Dotted path, then the path without the source-object prefix, then its last segment (as gate G1 does)."""
    key = path.split("(", 1)[0].strip()
    node: Any = payload
    for part in key.split("."):
        node = node.get(part) if isinstance(node, Mapping) else None
    if node is not None:
        return node
    for k in (key.split(".", 1)[-1], key.rsplit(".", 1)[-1], key):
        if k in payload:
            return payload[k]
    return None


def _normalise(value: Any, allowed: frozenset[str] | tuple[str, ...] | None) -> tuple[Any, bool]:
    """Vocabulary normalisation: trim, lower-case, spaces and hyphens to underscores, only if that hits an allowed value."""
    if allowed and isinstance(value, str) and value not in allowed:
        cand = value.strip().lower().replace(" ", "_").replace("-", "_")
        if cand in allowed:
            return cand, True
    return value, False


class Labeller:
    def __init__(self, view: OntologyView, definitions: Sequence[LabelDefinition] = (), *, now: Any = None) -> None:
        self.view = view
        self.definitions = tuple(definitions)
        self._now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"))

    # ---- public ------------------------------------------------------------------------------------
    def label(self, tenant_id: str, source_system: str, source_object: str, payload: Mapping[str, Any]) -> LabelledRecord:
        v = self.view
        pins = v.bundle.pins
        rec = LabelledRecord(
            tenant_id=tenant_id, entity_id=None, concept=None, ontology_level=None, ontology_pack_id=None,
            ontology_pack_version=None, ontology_version=pins.core_version, domain=None, source_system=source_system,
            source_type=source_object, source_id=None, recorded_at=self._now())
        if not tenant_id or not isinstance(tenant_id, str):
            return self._quarantine(rec, Q_TENANT, "tenant_id is required")
        system = v.bundle.mappings.get(source_system)
        if system is None:
            return self._quarantine(rec, Q_UNMAPPED_TYPE, f"unmapped type: no mapping for source system {source_system}")
        entry, ambiguous = self._classify(system.entries, source_object, payload)
        if ambiguous:
            return self._quarantine(rec, Q_AMBIGUOUS, "more than one mapping at the same level matches with different results: " + ", ".join(ambiguous))
        if entry is None:
            if system.on_unmapped == "evidence":
                rec.processing_status = EVIDENCE
                rec.explanation.append("no mapping for this source object; the source's on_unmapped policy is evidence")
                return rec
            keys = sorted({k for e in system.entries if e.source_object == source_object for k in e.when})
            hint = f" (check field: {', '.join(keys)})" if keys else ""
            return self._quarantine(rec, Q_UNMAPPED_TYPE, f"unmapped type: {source_system}/{source_object or '(none)'}{hint}")
        rec.mapping_rule_id = f"{source_system}:{entry.source_object}:{'|'.join(sorted(entry.when)) or '*'}@{entry.pack_level}"
        if entry.relationship:
            rec.processing_status = RELATIONSHIP
            rec.explanation.append(f"mapped to relationship {entry.relationship}; edges are built from relationship claims, not nodes")
            return rec
        if entry.entity is None:
            rec.processing_status = _CARRIER_STATUS.get(entry.role or "", EVIDENCE)
            rec.explanation.append(f"role {entry.role}: no node is created")
            return rec
        return self._build(rec, entry, source_object, payload)

    # ---- stages --------------------------------------------------------------------------------------
    def _classify(self, entries: Sequence[MappingEntry], source_object: str, payload: Mapping[str, Any]):
        hits = [e for e in entries if e.source_object == source_object and
                all(str(_lookup(payload, k, source_object)).lower() in {x.lower() for x in allowed} for k, allowed in e.when.items())]
        if not hits:
            return None, []
        top = [e for e in hits if e.pack_level == hits[0].pack_level]       # entries are most specific level first
        concepts = sorted({str(e.entity or e.relationship or e.role) for e in top})
        return (top[0], concepts) if len(concepts) > 1 else (top[0], [])

    def _build(self, rec: LabelledRecord, entry: MappingEntry, source_object: str, payload: Mapping[str, Any]) -> LabelledRecord:
        v = self.view
        concept = entry.entity or ""
        cdef = v.bundle.concepts[concept]
        rec.concept = concept
        rec.ontology_level = v.concept_level.get(concept, "core")
        rec.ontology_pack_id = v.concept_pack.get(concept, "core")
        rec.ontology_pack_version = next((p.version for p in v.bundle.pins.packs if p.id == rec.ontology_pack_id), v.bundle.pins.core_version)
        rec.domain = v.concept_domain.get(concept) or None
        rec.explanation.append(f"{rec.source_system}/{source_object} maps to {concept} by rule {rec.mapping_rule_id} (deterministic, confidence 1.0)")
        rec.field_provenance["concept"] = FieldProvenance(concept, entry.pack_level, rec.mapping_rule_id or "", "application-pack mapping",
                                                         [{"layer": entry.pack_level, "source": rec.mapping_rule_id, "value": concept}])
        # 1. extraction + 5. normalisation
        eff = effective_properties(v, concept, [d for d in self.definitions if d.tenant_id == rec.tenant_id])
        deferred: set[str] = set()
        values: dict[str, Any] = {}
        for target, source in entry.fields.items():
            if "(" in source:
                deferred.add(target)         # another pack translates this value; do not check it here
            raw = _lookup(payload, source, source_object)
            if raw is None or raw == "" or raw == []:
                continue
            ep = eff.get(target)
            if target not in deferred:
                raw, changed = _normalise(raw, ep.allowed_values if ep else None)
                if changed:
                    rec.explanation.append(f"normalised {target} to {raw!r}")
            values[target] = raw
            rec.field_provenance[target] = FieldProvenance(raw, entry.pack_level, source.split("(")[0].strip(), "mapped from source field",
                                                          [{"layer": entry.pack_level, "source": source.split("(")[0].strip(), "value": raw}])
        # 4. enrichment: defaults from active definitions, most specific layer wins (explained)
        for name, ep in eff.items():
            if name not in values and ep.default is not None:
                values[name] = ep.default
                rec.field_provenance[name] = FieldProvenance(ep.default, ep.value_layer, "default", f"default from {ep.value_layer} level",
                                                            ep.contributions)
        # 3. labels
        self._assign_labels(rec, entry, source_object, payload)
        # unpack common attributes
        for key in _COMMON:
            if key in values:
                setattr(rec, key, values.pop(key))
        for key in ("valid_from", "valid_to", "source_version", "source_uri", "owner_ref", "acl_ref", "acl_state", "sensitivity"):
            if getattr(rec, key) is None and payload.get(key) is not None:
                setattr(rec, key, payload[key])
        rec.properties = values
        if rec.source_id is None and payload.get("source_id"):
            rec.source_id = str(payload["source_id"])
        rec.valid_from = rec.valid_from or rec.recorded_at
        rec.evidence_ref = rec.source_uri or (f"{rec.source_system}:{rec.source_id}" if rec.source_id else None)
        # 6. validation
        self._validate(rec, cdef, eff, deferred)
        if rec.source_id:
            rec.entity_id = str(payload.get("entity_id") or derive_entity_id(rec.tenant_id, concept, rec.source_system, rec.source_id))
        if any(r.severity == "error" for r in rec.validation_results):
            return self._quarantine(rec, Q_SCHEMA, "; ".join(r.message for r in rec.validation_results if r.severity == "error"))
        rec.processing_status = LABELLED
        return rec

    def _assign_labels(self, rec: LabelledRecord, entry: MappingEntry, source_object: str, payload: Mapping[str, Any]) -> None:
        v = self.view
        concept = rec.concept or ""
        core = v.core_concept(concept)
        rec.custom_labels.append(Label(concept, rec.ontology_level or "core", "concept", rec.ontology_pack_id or "core", "canonical concept"))
        if core != concept:
            rec.custom_labels.append(Label(core, "core", "concept", "core", f"{concept} is a subclass of {core}"))
        if rec.domain:
            rec.custom_labels.append(Label(rec.domain, "core", "domain", "core", "semantic domain of the concept"))
        term = str(payload.get("source_term") or "").lower()
        if term and v.glossary.get(term) == concept:
            rec.custom_labels.append(Label(str(payload["source_term"]), "organization", "alias", "glossary", "organisation glossary term"))
        for d in sorted(self.definitions, key=lambda x: (LEVELS.index(x.level), x.id)):
            if not d.active or d.tenant_id != rec.tenant_id or d.parent_concept not in v.ancestors(concept):
                continue
            if d.source_systems and rec.source_system not in d.source_systems:
                continue
            if d.source_types and source_object not in d.source_types:
                continue
            if any(str(_lookup(payload, k, source_object)).lower() not in {x.lower() for x in allowed} for k, allowed in d.when.items()):
                continue
            kind = "alias" if d.aliases or d.level == "organization" else "custom"
            rec.custom_labels.append(Label(d.display_name, d.level, kind, d.id, f"definition {d.id} v{d.version} applies"))

    def _validate(self, rec: LabelledRecord, cdef: Any, eff: Mapping[str, Any], deferred: set[str]) -> None:
        out = rec.validation_results
        v = self.view
        for name, ep in eff.items():
            value = rec.name if name == "name" else rec.properties.get(name, getattr(rec, name, None) if name in _COMMON else None)
            if value is None or value == "" or value == []:
                if ep.required:
                    out.append(ValidationResult("required_missing", name, f"missing required attribute: {name}"))
                continue
            if name in deferred:
                continue
            attr = cdef.attributes.get(name)
            multi = bool(attr and attr.multi)
            p = PropertyDef(name, ep.type, ep.required, None, ep.allowed_values, ep.pattern, None, "many" if multi else "one")
            if ep.type == "enum" and ep.allowed_values is not None:
                bad = "" if all(str(i) in ep.allowed_values for i in (value if isinstance(value, (list, tuple)) else [value])) else f"{value!r} is not an allowed value"
            else:
                bad = check_value(p, value) if ep.type in ("integer", "decimal", "boolean", "date", "datetime") or ep.pattern or ep.allowed_values else ""
            if bad:
                out.append(ValidationResult("vocab_value" if ep.allowed_values else "type", name, f"value not allowed for {name}: {bad}"))
        for req in ("source_id",):
            if not getattr(rec, req):
                out.append(ValidationResult("required_missing", req, f"missing required attribute: {req}"))
        if rec.sensitivity is not None and (isinstance(rec.sensitivity, bool) or rec.sensitivity not in (0, 1, 2, 3)):
            out.append(ValidationResult("vocab_value", "sensitivity", "sensitivity must be 0 to 3"))
        if rec.acl_state is not None and rec.acl_state not in v.vocabulary("acl_state"):
            out.append(ValidationResult("vocab_value", "acl_state", "acl_state must be known, unknown or stale"))
        try:
            if rec.valid_to and rec.valid_from and _ts(rec.valid_from) > _ts(rec.valid_to):
                out.append(ValidationResult("temporal", "valid_to", "valid_from must not be later than valid_to"))
        except (ValueError, TypeError):
            out.append(ValidationResult("temporal", "valid_from", "valid_from and valid_to must be ISO 8601"))
        if rec.acl_state in (None, "unknown", "stale"):
            out.append(ValidationResult("acl", "acl_state", "permissions unknown or stale: owners only until harvested", "warning"))

    @staticmethod
    def _quarantine(rec: LabelledRecord, code: str, reason: str) -> LabelledRecord:
        rec.processing_status = QUARANTINED
        rec.reason_code = code
        rec.explanation.append(f"quarantined {code}: {reason}")
        if not any(r.message == reason for r in rec.validation_results):
            rec.validation_results.append(ValidationResult("quarantine", "", reason))
        return rec


def _ts(text: str) -> datetime:
    return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
