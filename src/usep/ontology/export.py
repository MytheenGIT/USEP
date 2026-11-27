"""The ontology as JSON for the console (definitions only: no tenant data, no source data, no secrets).

The shape is the contract in docs/ui-ontology-view-brief.md. It is built from the one loader's bundle, so the UI shows
exactly what the pipeline enforces. The API serves it for the tenant's pinned packs; this module does no I/O.
"""
from __future__ import annotations

from typing import Any

from usep.ontology_runtime.model import OntologyBundle


def to_dto(b: OntologyBundle) -> dict[str, Any]:
    concepts = []
    for cid, c in sorted(b.concepts.items()):
        attrs = []
        for a in b.attributes_of(cid):
            owner = next((x for x in reversed(b.ancestors(cid)) if any(y.name == a.name for y in b.concepts[x].attributes)), cid)
            attrs.append({"name": a.name, "type": a.type, "required": a.required, "multi": a.multi,
                          "values_ref": a.values_ref, "defined_in": owner})
        concepts.append({"id": cid, "domain": c.domain, "level": c.level, "pack_id": c.pack_id, "parent": c.parent,
                         "description": c.description, "role_only": c.role_only, "attributes": attrs})
    return {
        "ontology_version": b.release.core_version,
        "digest": b.release.digest,
        "packs": [{"id": p.id, "level": p.level, "version": p.version, "status": p.status, "signed": p.signed,
                   "reference_only": p.reference_only} for p in b.release.packs],
        "domains": list(b.domains),
        "concepts": concepts,
        "relationships": [{"id": r.id, "from": list(r.from_types), "to": list(r.to_types), "level": r.level,
                           "same_type": r.same_type} for _, r in sorted(b.relationships.items())],
        "vocabularies": {k: [str(v) for v in vs] for k, vs in sorted(b.vocabularies.items()) if k != "domains"},
        "templates": [{"name": t.name, "pack_id": t.pack_id or "core", "max_depth": t.max_depth, "fanout_cap": t.fanout_cap}
                      for _, t in sorted(b.templates.items())],
        "policies": [{"id": p.id, "effect": p.effect, "level": p.level} for p in b.policies],
        "glossary": dict(sorted(b.glossary.items())),
    }
