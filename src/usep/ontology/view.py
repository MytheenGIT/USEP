"""Read-only facts about the pinned ontology that OntologyBundle does not keep: each concept's domain,
the level that defined it, relationship endpoint rules, org glossary and source precedence.

Nothing here writes a definition. Packs are additive, so a pack concept's domain is its parent's.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from usep.ontology.bundle import OntologyBundle

LEVELS = ("core", "industry", "organization", "application", "project")   # least to most specific


@dataclass(frozen=True, slots=True)
class RelationshipRule:
    id: str
    sources: frozenset[str]
    targets: frozenset[str]
    same_type: bool = False


class OntologyView:
    """Interpretation: 'Domain Ontology' = the industry pack level (ontology/README.md, guide section 4); the
    seven semantic domains are the `domain` attribute of a node, not a pack level.

    Everything here comes from the one loader's bundle (`bundle.runtime`); nothing is read from disk."""

    def __init__(self, bundle: OntologyBundle, root: str | Path | None = None) -> None:
        rb = bundle.runtime
        if rb is None:
            raise ValueError("OntologyView needs a bundle made by OntologyBundle.load")
        self.bundle = bundle
        self.root = Path(root) if root is not None else None
        self.domains = list(rb.domains)
        self.common_attributes: frozenset[str] = frozenset(a.name for a in (*rb.common_required, *rb.common_optional))
        self.concept_level: dict[str, str] = {cid: c.level for cid, c in rb.concepts.items()}
        self.concept_domain: dict[str, str] = {cid: str(c.domain or "") for cid, c in rb.concepts.items()}
        self.concept_description: dict[str, str] = {cid: c.description for cid, c in rb.concepts.items()}
        self.concept_pack: dict[str, str] = {cid: c.pack_id for cid, c in rb.concepts.items()}
        self.relationship_rules: dict[str, RelationshipRule] = {
            r.id: RelationshipRule(r.id, frozenset(r.from_types), frozenset(r.to_types), r.same_type)
            for r in rb.relationships.values()}
        self.glossary: dict[str, str] = {str(t).lower(): c for t, c in rb.glossary.items()}   # organisation term -> concept
        self.precedence: dict[str, list[str]] = {k: [str(x) for x in (v.get("order", []) if isinstance(v, Mapping) else [])]
                                                 for k, v in rb.precedence.items()}
        self.source_system_priority: list[str] = list(rb.source_priority)

    # ---- queries ----------------------------------------------------------------------------------
    def ancestors(self, concept: str) -> list[str]:
        """The concept followed by its parents, nearest first (a pack subclass resolves to a core concept)."""
        out, cur = [], concept
        while cur and cur not in out:
            out.append(cur)
            cur = self.bundle.concepts[cur].parent if cur in self.bundle.concepts else None
        return out

    def core_concept(self, concept: str) -> str:
        return self.ancestors(concept)[-1]

    def is_a(self, concept: str, ancestor: str) -> bool:
        return ancestor in self.ancestors(concept)

    def endpoint_ok(self, relation: str, source_concept: str, target_concept: str) -> str | None:
        """None if the relationship may join the two concepts, else the reason it may not."""
        rule = self.relationship_rules.get(relation)
        if rule is None:
            return f"unknown relationship {relation}"
        if not (set(self.ancestors(source_concept)) & rule.sources):
            return f"{relation} cannot start at {source_concept} (allowed: {', '.join(sorted(rule.sources))})"
        if not (set(self.ancestors(target_concept)) & rule.targets):
            return f"{relation} cannot end at {target_concept} (allowed: {', '.join(sorted(rule.targets))})"
        if rule.same_type and self.core_concept(source_concept) != self.core_concept(target_concept):
            return f"{relation} joins the same type only ({source_concept} -> {target_concept})"
        return None

    def vocabulary(self, name: str) -> frozenset[str]:
        return self.bundle.vocabularies.get(name, frozenset())

    def versions(self) -> dict[str, Any]:
        return self.bundle.pins.as_dict()
