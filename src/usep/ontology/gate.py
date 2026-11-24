"""Gate G1: check a source record against the pinned ontology (LLD 2.1, 4.5; HLD 6 Table 9 constraints).

The gate answers three questions about one record, in order:
1. What is it? The application pack's mapping for the record's source system turns the source
   object (`attributes["kind"]`, else `entity_type`) into a core concept.
2. Is that allowed? A source object with no mapping follows the mapping file's `on_unmapped`
   policy: `quarantine` (the record is rejected with Q-SCHEMA and the words "unmapped type") or
   `evidence` (it passes and can still support other entities).
3. Is it well formed? For a mapped concept, every required attribute is present and every
   enumerated attribute holds an allowed value.

Statuses that pass: mapped, relationship, carrier, unmodelled, evidence. A record that fails is
quarantined by the pipeline; nothing is guessed and nothing is dropped.

This validator reads the YAML definitions. The Turtle shapes in ontology/shapes/ are checked by pack
CI with rdflib. Both come from the same core, and a test keeps them in step on the cases that matter,
so rdflib stays out of the run-time path.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

from usep.core.models import SourceRecord
from usep.ontology.bundle import AttributeDef, MappingEntry, OntologyBundle, _DATE_RE

MAPPED, RELATIONSHIP, CARRIER, UNMODELLED, EVIDENCE, REJECTED = (
    "mapped", "relationship", "carrier", "unmodelled", "evidence", "rejected",
)


@dataclass(frozen=True, slots=True)
class GateOutcome:
    status: str
    concept: str | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status != REJECTED


class OntologyGate:
    def __init__(self, bundle: OntologyBundle) -> None:
        self.bundle = bundle
        self.stats: Counter[str] = Counter()   # how many records took each path; for the metrics later

    def check(self, record: SourceRecord) -> GateOutcome:
        outcome = self._check(record)
        self.stats[outcome.status] += 1
        return outcome

    # ---- steps ------------------------------------------------------------------------------------
    def _check(self, record: SourceRecord) -> GateOutcome:
        attributes = record.attributes
        kind = str(attributes.get("kind") or record.entity_type or "")
        system = self.bundle.mappings.get(record.source_system)
        if system is None:
            return GateOutcome(REJECTED, detail=f"unmapped type: no mapping for source system {record.source_system}")
        entry = self._find(system.entries, kind, attributes)
        if entry is None:
            if system.on_unmapped == "evidence":
                return GateOutcome(EVIDENCE)
            # name the field that tells types apart (not its value), so the owner knows where to look
            keys = sorted({k for e in system.entries if e.source_object == kind for k in e.when})
            hint = f" ({', '.join(keys)})" if keys else ""
            return GateOutcome(REJECTED, detail=f"unmapped type: {record.source_system}/{kind or '(no kind)'}{hint}")
        if entry.relationship:
            return GateOutcome(RELATIONSHIP)
        if entry.entity is None:
            return GateOutcome(entry.role if entry.role in (CARRIER, UNMODELLED, EVIDENCE) else EVIDENCE)
        problem = self._validate(entry, attributes)
        if problem:
            return GateOutcome(REJECTED, entry.entity, problem)
        return GateOutcome(MAPPED, entry.entity)

    @staticmethod
    def _find(entries: list[MappingEntry], kind: str, attributes: Mapping[str, Any]) -> MappingEntry | None:
        for e in entries:   # most specific pack level first
            if e.source_object != kind:
                continue
            if all(str(attributes.get(k)) in allowed for k, allowed in e.when.items()):
                return e
        return None

    def _validate(self, entry: MappingEntry, attributes: Mapping[str, Any]) -> str:
        concept = self.bundle.concepts[entry.entity or ""]
        mapped: dict[str, tuple[Any, bool]] = {}   # ontology attribute -> (value, translated by another pack)
        for onto_attr, source in entry.fields.items():
            translated = "(" in source               # "issue.status (project pack maps this)": value is not checked here
            key = source.split("(", 1)[0].strip()
            value = attributes.get(key, attributes.get(key.rsplit(".", 1)[-1]))
            mapped[onto_attr] = (value, translated)
        for name, attr in concept.attributes.items():
            value, translated = mapped.get(name, (None, False))   # only mapped fields count: a source field that
            # happens to share an ontology attribute name does not mean the same thing
            if value is None or value == "" or value == []:
                if attr.required:
                    return f"missing required attribute: {name}"
                continue
            if translated:
                continue
            problem = self._check_value(attr, value)
            if problem:
                return problem
        return ""

    def _check_value(self, attr: AttributeDef, value: Any) -> str:
        items = value if attr.multi and isinstance(value, (list, tuple)) else [value]
        allowed = self.bundle.vocabularies.get(attr.values_ref) if attr.values_ref else None
        for item in items:
            if attr.type == "enum":
                if allowed is not None and str(item).strip().lower() not in allowed:
                    return f"value not allowed for {attr.name}"
            elif attr.type == "date":
                if not isinstance(item, str) or not _DATE_RE.match(item):
                    return f"{attr.name} must be a date (YYYY-MM-DD)"
            elif attr.type == "string":
                if not isinstance(item, str):
                    return f"{attr.name} must be text"
        return ""
