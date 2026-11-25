"""Read-only facts about the pinned ontology that OntologyBundle does not keep: each concept's domain,
the level that defined it, relationship endpoint rules, org glossary and source precedence.

Nothing here writes a definition. Packs are additive, so a pack concept's domain is its parent's.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from usep.ontology.bundle import OntologyBundle, _FOLDER_FOR_LEVEL

LEVELS = ("core", "industry", "organization", "application", "project")   # least to most specific


@dataclass(frozen=True, slots=True)
class RelationshipRule:
    id: str
    sources: frozenset[str]
    targets: frozenset[str]
    same_type: bool = False


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}


class OntologyView:
    """Interpretation: 'Domain Ontology' = the industry pack level (ontology/README.md, guide section 4); the
    seven semantic domains are the `domain` attribute of a node, not a pack level."""

    def __init__(self, bundle: OntologyBundle, root: str | Path) -> None:
        self.bundle = bundle
        self.root = Path(root)
        core = self.root / "core"
        self.domains = [d["id"] for d in _yaml(core / "domains.yml").get("domains", [])]
        ca = _yaml(core / "common-attributes.yml")
        self.common_attributes: frozenset[str] = frozenset(
            a["name"] for part in ("required", "optional") for a in (ca.get("node") or {}).get(part, []))
        raw = {c["id"]: c for c in _yaml(core / "concepts.yml").get("concepts", [])}
        self.concept_level: dict[str, str] = {cid: "core" for cid in raw}
        self.concept_domain: dict[str, str] = {cid: str(c.get("domain", "")) for cid, c in raw.items()}
        self.concept_description: dict[str, str] = {cid: str(c.get("description", "")) for cid, c in raw.items()}
        self.concept_pack: dict[str, str] = {cid: "core" for cid in raw}
        self.relationship_rules: dict[str, RelationshipRule] = {}
        for r in _yaml(core / "relationships.yml").get("relationships", []):
            self.relationship_rules[r["id"]] = RelationshipRule(r["id"], frozenset(r["from"]), frozenset(r["to"]), bool(r.get("same_type")))
        self.glossary: dict[str, str] = {}              # organisation term (lower case) -> core/pack concept
        self.precedence: dict[str, list[str]] = {}
        self.source_system_priority: list[str] = []
        self.pack_dirs: dict[str, Path] = {}
        for pin in bundle.pins.packs:
            pdir = self._pack_dir(pin.id, pin.level)
            self.pack_dirs[pin.id] = pdir
            for c in _yaml(pdir / "concepts.yml").get("concepts", []):
                self.concept_level[c["id"]] = pin.level
                self.concept_pack[c["id"]] = pin.id
                self.concept_description[c["id"]] = str(c.get("description", ""))
                self.concept_domain[c["id"]] = self.concept_domain.get(c.get("subclass_of"), "")
            for r in _yaml(pdir / "concepts.yml").get("relationships", []):
                self.relationship_rules[r["id"]] = RelationshipRule(r["id"], frozenset(r["from"]), frozenset(r["to"]), bool(r.get("same_type")))
            for t in _yaml(pdir / "glossary.yml").get("terms", []):
                if t.get("maps_to") in bundle.concepts and not str(t.get("term", "")).startswith("<"):
                    self.glossary[str(t["term"]).lower()] = t["maps_to"]
            prec = _yaml(pdir / "precedence.yml")
            if prec:
                self.source_system_priority = [str(x) for x in prec.get("source_system_priority", [])]
                self.precedence.update({k: [str(x) for x in v.get("order", [])] for k, v in (prec.get("attributes") or {}).items()})

    def _pack_dir(self, pack_id: str, level: str) -> Path:
        base = self.root / "packs" / _FOLDER_FOR_LEVEL[level]
        for d in sorted(base.iterdir()):
            m = _yaml(d / "pack.yml") if d.is_dir() else {}
            if m.get("id") == pack_id:
                return d
        raise FileNotFoundError(pack_id)

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
