"""Ontology mapping for one canonical record: application-pack mapping, project-pack state translation, gate G1.

`map_record` and `validate` are the gate in usep.ontology_runtime.gate. This module adds the one translation the mappings
leave to the project pack: a source status to a core state (Jira 'In Review' to change_state in_review, a merge
request state to change_state, and a requirement's status). A status with no rule is quarantined (Q-STATE), never guessed (project-pack workflow.yml).
"""
from __future__ import annotations

from typing import Any, Mapping

from usep.core.ids import uuid7
from usep.ontology_runtime.gate import Candidate, GateResult, Quarantine, map_record, validate
from usep.ontology_runtime.model import OntologyBundle
from usep.pipeline.state_tables import STATE_TABLES

Q_STATE = "Q-STATE"

def _translate(bundle: OntologyBundle, cand: Candidate, payload: Mapping[str, Any], source_object: str,
               system_of: str) -> GateResult:
    attrs = dict(cand.attributes)
    scope = payload.get(source_object) or {}
    for system, concept, attr, src_field, table in STATE_TABLES:
        if cand.type != concept or system != system_of:
            continue
        raw_state = scope.get(src_field)
        if raw_state in (None, ""):
            attrs.pop(attr, None)                             # nothing to translate; the gate reports if required
            continue
        rules = bundle.workflow.get(table) or []
        hit = next((r[attr] for r in rules if str(r.get("source_state")) == str(raw_state)), None)
        if hit is None:
            return GateResult(False, quarantine=Quarantine(
                Q_STATE, f"no {table} rule for the source value of {source_object}.{src_field}", (source_object, src_field)))
        attrs[attr] = hit
    return GateResult(True, Candidate(cand.kind, cand.type, attrs, cand.from_type, cand.to_type))


def to_candidate(bundle: OntologyBundle, source_system: str, source_object: str,
                 payload: Mapping[str, Any]) -> GateResult:
    """Map, translate states, and return the result without the common node attributes (the worker adds those)."""
    mapped = map_record(bundle, source_system, source_object, payload)
    if not mapped.ok or mapped.candidate.kind != "node":
        return mapped
    return _translate(bundle, mapped.candidate, payload, source_object, source_system)


def validate_with_common(bundle: OntologyBundle, cand: Candidate, common: Mapping[str, Any]) -> GateResult:
    """Gate G1 over the candidate plus common attributes. entity_id here is a throwaway UUID v7 used only to pass
    the check: the resolver and fabric writer assign the real id (step 6), so replaying a record cannot mint a
    second entity."""
    if cand.kind == "node":
        cand = Candidate("node", cand.type, {**cand.attributes, **common, "entity_id": str(uuid7())})
    return validate(bundle, cand)
