"""Dump what consumers of usep.ontology can observe, for the golden comparison in test_ontology_unified.py."""
from dataclasses import asdict
from pathlib import Path

from usep.ontology.bundle import OntologyBundle
from usep.ontology.view import OntologyView

ROOT = Path(__file__).resolve().parents[1] / "ontology"
COMBOS = {
    "pipeline_packs": ["app.app-reference", "org.org-reference", "project.project-reference"],
    "banking_stack": ["industry.banking-reference", "org.org-reference", "app.app-reference", "project.project-reference"],
    "retail_stack": ["industry.retail-reference", "app.retail-app-reference"],
    "core_only": [],
}


def snapshot(ids):
    b = OntologyBundle.load(ROOT, ids, allow_reference=True)
    v = OntologyView(b, ROOT)
    return {
        "core_version": b.pins.core_version,
        "packs": [(p.id, p.level, p.version) for p in b.pins.packs],
        "concepts": {k: {"parent": c.parent, "attrs": {n: asdict(a) for n, a in sorted(c.attributes.items())}} for k, c in sorted(b.concepts.items())},
        "relationships": sorted(b.relationships),
        "vocab": {k: sorted(x) for k, x in sorted(b.vocabularies.items())},
        "mappings": {s: {"on_unmapped": m.on_unmapped, "entries": [
            [e.source_object, {k: list(x) for k, x in sorted(e.when.items())}, e.entity, e.relationship, e.role, dict(sorted(e.fields.items())), e.pack_level]
            for e in m.entries]} for s, m in sorted(b.mappings.items())},
        "systems": {k: asdict(s) for k, s in sorted(b.systems.items())},
        "view": {"domains": v.domains, "common": sorted(v.common_attributes), "level": dict(sorted(v.concept_level.items())),
                 "domain": dict(sorted(v.concept_domain.items())), "descr": dict(sorted(v.concept_description.items())),
                 "pack": dict(sorted(v.concept_pack.items())),
                 "rules": {k: [sorted(r.sources), sorted(r.targets), r.same_type] for k, r in sorted(v.relationship_rules.items())},
                 "glossary": dict(sorted(v.glossary.items())), "precedence": dict(sorted(v.precedence.items())),
                 "priority": v.source_system_priority},
    }
