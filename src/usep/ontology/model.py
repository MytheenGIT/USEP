"""Immutable in-memory view of the ontology (core plus pinned packs). Definitions only, never tenant data."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

LEVEL_ORDER = ("core", "industry", "organization", "application", "project")   # least to most specific (HLD 6.1)


@dataclass(frozen=True)
class Attribute:
    name: str
    type: str = "string"
    required: bool = False
    multi: bool = False
    values: tuple[Any, ...] | None = None        # resolved from values_ref; None = not enumerated
    values_ref: str | None = None                # the vocabulary's name, when the attribute is enumerated


@dataclass(frozen=True)
class Concept:
    id: str
    domain: str | None
    level: str
    parent: str | None = None                    # pack concepts are subclasses of a core concept
    role_only: bool = False
    attributes: tuple[Attribute, ...] = ()
    description: str = ""
    pack_id: str = "core"                        # the pack that defined it


@dataclass(frozen=True)
class Relationship:
    id: str
    from_types: tuple[str, ...]
    to_types: tuple[str, ...]
    level: str = "core"
    same_type: bool = False                      # both ends must resolve to one core concept


@dataclass(frozen=True)
class Policy:
    id: str
    effect: str                                  # deny | require_approval | restrict_to_owners. Never allow.
    level: str
    when: Mapping[str, Any] = field(default_factory=dict)
    approvals: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Template:
    name: str
    max_depth: int
    fanout_cap: int
    steps: tuple[str, ...]
    pack_id: str = ""                          # empty for a core template


@dataclass(frozen=True)
class Mapping_:
    """One source-object to core-type rule from an application pack."""
    pack_id: str
    source_system: str
    source_object: str
    when: Mapping[str, tuple[str, ...]]
    entity: str | None = None
    relationship: str | None = None
    from_entity: str | None = None
    to_entity: str | None = None
    fields: Mapping[str, str] = field(default_factory=dict)
    evidence_only: bool = False                  # matched, but no entity: the text is kept as evidence only
    level: str = ""                              # pack level that defined the rule
    role: str | None = None                      # carrier | unmodelled | evidence, for a record that makes no node


@dataclass(frozen=True)
class PackInfo:
    id: str
    level: str
    version: str
    status: str
    signed: bool
    reference_only: bool


@dataclass(frozen=True)
class System:
    """A system an application pack registers and maps to a core type (HLD 6 Table 10)."""
    system_id: str
    core_type: str
    source_systems: tuple[str, ...]
    regulatory_scope: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class OntologyRelease:
    """What a run records so it can finish under the version it started with (CC-18) and be replayed (HLD 6.1)."""
    core_version: str
    packs: tuple[PackInfo, ...]
    digest: str                                  # sha256 over every defining file

    def as_dict(self) -> dict[str, Any]:
        return {
            "core_version": self.core_version,
            "packs": [{"id": p.id, "level": p.level, "version": p.version} for p in self.packs],
            "digest": self.digest,
        }


@dataclass(frozen=True)
class OntologyBundle:
    release: OntologyRelease
    domains: tuple[str, ...]
    common_required: tuple[Attribute, ...]
    common_optional: tuple[Attribute, ...]
    vocabularies: Mapping[str, tuple[Any, ...]]
    concepts: Mapping[str, Concept]
    relationships: Mapping[str, Relationship]
    policies: tuple[Policy, ...]
    templates: Mapping[str, Template]
    mappings: tuple[Mapping_, ...]
    precedence: Mapping[str, Any]                # org pack: attribute -> ordered sources (placeholder until the workshop)
    glossary: Mapping[str, str]                  # org word -> core concept
    workflow: Mapping[str, Any] = field(default_factory=dict)   # project pack: source states -> core states
    systems: Mapping[str, System] = field(default_factory=dict)
    on_unmapped: Mapping[str, str] = field(default_factory=dict)   # source system -> quarantine | evidence
    source_priority: tuple[str, ...] = ()        # org pack: which source system wins when none is named per attribute

    def ancestors(self, concept_id: str) -> tuple[str, ...]:
        """The concept followed by its parents, so a subclass is accepted wherever its parent is."""
        out, cur = [], self.concepts.get(concept_id)
        while cur is not None and cur.id not in out:
            out.append(cur.id)
            cur = self.concepts.get(cur.parent) if cur.parent else None
        return tuple(out)

    def attributes_of(self, concept_id: str) -> tuple[Attribute, ...]:
        """Own attributes plus those inherited from parents. A subclass adds, never removes."""
        seen: dict[str, Attribute] = {}
        for cid in reversed(self.ancestors(concept_id)):
            for a in self.concepts[cid].attributes:
                seen[a.name] = a
        return tuple(seen.values())
