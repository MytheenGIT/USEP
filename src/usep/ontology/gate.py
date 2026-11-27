"""Gate G1: schema validation of every candidate before it is committed (HLD 5; guide section 3.5, 6.1).

Two steps. `map_record` turns a source record into a candidate node or edge through the application pack's
mappings. `validate` checks the candidate against the core rules: required attributes, allowed values, temporal
validity and, for edges, endpoint types. A failure never becomes a stored fact. It becomes a Quarantine entry with a
reason code. Quarantine keeps the reason and where it was found (field names), never the content.

The shapes in ontology/shapes/*.ttl are checked by pack CI. This gate reads the same rules from the YAML definitions
(the guide's section 8 says the run-time validator reads YAML, not Turtle).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from usep.ontology.model import OntologyBundle

Q_SCHEMA = "Q-SCHEMA"          # a rule failed
Q_UNMAPPED = "Q-UNMAPPED"      # 'unmapped type': no mapping matches the source object
_PATH = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)*$")


@dataclass(frozen=True)
class Candidate:
    kind: str                                    # node | edge | evidence
    type: str                                    # concept or relationship id
    attributes: Mapping[str, Any]
    from_type: str | None = None
    to_type: str | None = None


@dataclass(frozen=True)
class Quarantine:
    reason_code: str
    reason: str
    location: tuple[str, ...] = ()               # field names or source object: never values


@dataclass(frozen=True)
class GateResult:
    ok: bool
    candidate: Candidate | None = None
    quarantine: Quarantine | None = None


def _lookup(payload: Mapping[str, Any], path: str) -> Any:
    cur: Any = payload
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _when_matches(when: Mapping[str, tuple[str, ...]], source_object: str, payload: Mapping[str, Any]) -> bool:
    scope = payload.get(source_object) if isinstance(payload.get(source_object), Mapping) else {}
    for key, allowed in when.items():
        val = scope.get(key, payload.get(key))
        vals = list(val) if isinstance(val, (list, tuple, set)) else [val]
        if not allowed:                          # an empty list means 'none of these set' (for example no label)
            if any(v not in (None, "") for v in vals):
                return False
        elif not any(v in allowed for v in vals):
            return False
    return True


def map_record(bundle: OntologyBundle, source_system: str, source_object: str,
               payload: Mapping[str, Any]) -> GateResult:
    """Pick the mapping for this record. No match goes to quarantine as 'unmapped type'; it is never guessed or dropped."""
    for m in bundle.mappings:
        if m.source_system != source_system or m.source_object != source_object:
            continue
        if not _when_matches(m.when, source_object, payload):
            continue
        attrs: dict[str, Any] = {}
        for target, expr in m.fields.items():
            # An expression that is not a plain path (for example 'x (project pack maps this)') is a translation
            # the project pack owns. It is not built yet, so the field stays unset instead of being guessed.
            if _PATH.match(expr):
                val = _lookup(payload, expr)
                if val is not None:
                    attrs[target] = val
        if m.evidence_only:
            return GateResult(True, Candidate("evidence", "", attrs))
        if m.entity:
            return GateResult(True, Candidate("node", m.entity, attrs))
        return GateResult(True, Candidate("edge", m.relationship, attrs, m.from_entity, m.to_entity))
    return GateResult(False, quarantine=Quarantine(
        Q_UNMAPPED, f"unmapped type: no mapping for {source_system}/{source_object}", (source_object,)))


def _is_uuid7(v: Any) -> bool:
    try:
        return uuid.UUID(str(v)).version == 7
    except ValueError:
        return False


def _parse_dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def validate(bundle: OntologyBundle, cand: Candidate) -> GateResult:
    """Check a candidate. Collects every failure so the steward sees them all at once."""
    bad: list[tuple[str, str]] = []                          # (field, reason)
    if cand.kind == "evidence":
        return GateResult(True, cand)

    if cand.kind == "edge":
        rel = bundle.relationships.get(cand.type)
        if rel is None:
            return _fail(f"unknown relationship type {cand.type}", (cand.type,))
        for end, t, allowed in (("from", cand.from_type, rel.from_types), ("to", cand.to_type, rel.to_types)):
            if t not in bundle.concepts or not set(bundle.ancestors(t)) & set(allowed):
                bad.append((end, f"{end} type {t} not allowed for {rel.id}"))
        for name, lo, hi in (("weight", 0, 1), ("confidence", 0, 1)):
            v = cand.attributes.get(name)
            if v is not None and not (isinstance(v, (int, float)) and lo <= v <= hi):
                bad.append((name, f"{name} must be between {lo} and {hi}"))
        return _result(cand, bad)

    concept = bundle.concepts.get(cand.type)
    if concept is None:
        return _fail(f"unknown concept {cand.type}", (cand.type,))
    a = cand.attributes
    for attr in bundle.common_required:
        if a.get(attr.name) in (None, ""):
            bad.append((attr.name, "required attribute missing"))
    if "tenant_id" in a and not _is_uuid7(a["tenant_id"]) and not _valid_uuid(a["tenant_id"]):
        bad.append(("tenant_id", "not a UUID"))
    if a.get("entity_id") not in (None, "") and not _is_uuid7(a["entity_id"]):
        bad.append(("entity_id", "must be a UUID v7"))
    if a.get("domain") not in (None, "") and a["domain"] not in bundle.domains:
        bad.append(("domain", "not one of the semantic domains"))
    if a.get("sensitivity") is not None and a["sensitivity"] not in bundle.vocabularies["sensitivity"]:
        bad.append(("sensitivity", "must be 0 to 3"))
    if a.get("acl_state") is not None and a["acl_state"] not in bundle.vocabularies["acl_state"]:
        bad.append(("acl_state", "must be known, unknown or stale"))
    vf, vt = _parse_dt(a.get("valid_from")), _parse_dt(a.get("valid_to"))
    for name, raw, parsed in (("valid_from", a.get("valid_from"), vf), ("valid_to", a.get("valid_to"), vt),
                              ("recorded_at", a.get("recorded_at"), _parse_dt(a.get("recorded_at")))):
        if raw not in (None, "") and parsed is None:
            bad.append((name, "not an ISO 8601 timestamp"))
    if vf and vt and vf > vt:
        bad.append(("valid_to", "valid_from is later than valid_to"))

    for attr in bundle.attributes_of(cand.type):
        val = a.get(attr.name)
        if val in (None, ""):
            if attr.required:
                bad.append((attr.name, "required attribute missing"))
            continue
        if attr.values is not None:
            for v in (val if attr.multi and isinstance(val, (list, tuple)) else [val]):
                if v not in attr.values:
                    bad.append((attr.name, "value not in the controlled vocabulary"))
    return _result(cand, bad)


def _valid_uuid(v: Any) -> bool:
    try:
        uuid.UUID(str(v))
        return True
    except ValueError:
        return False


def _fail(reason: str, loc: tuple[str, ...]) -> GateResult:
    return GateResult(False, quarantine=Quarantine(Q_SCHEMA, reason, loc))


def _result(cand: Candidate, bad: list[tuple[str, str]]) -> GateResult:
    if not bad:
        return GateResult(True, cand)
    return _fail("; ".join(f"{f}: {r}" for f, r in bad), tuple(dict.fromkeys(f for f, _ in bad)))
