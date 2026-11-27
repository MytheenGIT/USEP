"""A read-only view of the ontology for labelling and the graph (HLD 6.1: a tenant pins exact pack versions).

There is one loader: `usep.ontology_runtime.load_ontology` (fail closed, every problem listed, the digest of every
defining file). This module no longer reads YAML. `OntologyBundle.load` calls that loader and reshapes its result into
the types labelling and the graph use, so the two run-times can never disagree about what a pack defines (D7).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from usep.core.config import Config
from usep.ontology_runtime import load_ontology, resolve_pins
from usep.ontology_runtime.model import OntologyBundle as RuntimeBundle

LEVEL_ORDER = ("industry", "organization", "application", "project")   # least to most specific (HLD 6.1)


# ---- value objects -------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PackPin:
    id: str
    level: str
    version: str


@dataclass(frozen=True, slots=True)
class OntologyPins:
    """What a package records: the core version, each pinned pack, and a digest of every file."""

    core_version: str
    packs: tuple[PackPin, ...]
    digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "core": self.core_version,
            "packs": [{"id": p.id, "level": p.level, "version": p.version} for p in self.packs],
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class AttributeDef:
    name: str
    type: str = "string"
    required: bool = False
    multi: bool = False
    values_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ConceptDef:
    id: str
    parent: str | None
    attributes: Mapping[str, AttributeDef]   # includes the parent's, so a subclass inherits them


@dataclass(frozen=True, slots=True)
class MappingEntry:
    source_object: str
    when: Mapping[str, tuple[str, ...]]
    entity: str | None
    relationship: str | None
    role: str | None
    fields: Mapping[str, str]
    pack_level: str


@dataclass(frozen=True, slots=True)
class SystemDef:
    """A system an application pack registers and maps to a core type (HLD 6 Table 10)."""

    system_id: str
    core_type: str
    source_systems: tuple[str, ...]
    regulatory_scope: tuple[str, ...]
    status: str


@dataclass(slots=True)
class SourceMapping:
    source_system: str
    on_unmapped: str = "quarantine"          # quarantine | evidence
    entries: list[MappingEntry] = field(default_factory=list)   # most specific level first


# ---- the bundle ------------------------------------------------------------------------------------
class OntologyBundle:
    def __init__(
        self,
        pins: OntologyPins,
        concepts: Mapping[str, ConceptDef],
        relationships: frozenset[str],
        vocabularies: Mapping[str, frozenset[str]],
        mappings: Mapping[str, SourceMapping],
        systems: Mapping[str, SystemDef] | None = None,
        runtime: RuntimeBundle | None = None,
    ) -> None:
        self.pins = pins
        self.concepts = concepts
        self.relationships = relationships
        self.vocabularies = vocabularies
        self.mappings = mappings
        self.systems = systems or {}
        self.runtime = runtime            # the loader's own bundle: levels, domains, glossary, precedence, templates

    @classmethod
    def load(
        cls,
        root: str | Path,
        pack_ids: Sequence[str] = (),
        *,
        allow_reference: bool = False,
        require_signed: bool = False,
    ) -> "OntologyBundle":
        """Load the core and the named packs at the versions the checkout holds. Raises OntologyLoadError."""
        root = Path(root)
        pins = resolve_pins(root, pack_ids)
        rb = load_ontology(root, pins, allow_reference_only=allow_reference, allow_unsigned=not require_signed)
        return cls.from_runtime(rb)

    @classmethod
    def from_runtime(cls, rb: RuntimeBundle) -> "OntologyBundle":
        concepts = {
            cid: ConceptDef(cid, c.parent, {a.name: AttributeDef(a.name, a.type, a.required, a.multi, a.values_ref)
                                            for a in rb.attributes_of(cid)})
            for cid, c in rb.concepts.items()}
        rank = {lv: i for i, lv in enumerate(LEVEL_ORDER)}
        by_system: dict[str, SourceMapping] = {}
        # most specific pack level first; within a level the loader's order (file order) is kept
        for m in sorted(rb.mappings, key=lambda m: -rank.get(m.level, -1)):
            sm = by_system.setdefault(m.source_system, SourceMapping(m.source_system, rb.on_unmapped.get(m.source_system, "quarantine")))
            sm.entries.append(MappingEntry(
                source_object=m.source_object, when=dict(m.when), entity=m.entity, relationship=m.relationship,
                role=m.role, fields={str(k): str(v) for k, v in m.fields.items()}, pack_level=m.level))
        for system, policy in rb.on_unmapped.items():
            by_system.setdefault(system, SourceMapping(system, policy))
        packs = tuple(PackPin(p.id, p.level, p.version) for p in rb.release.packs if p.level != "core")
        pins = OntologyPins(rb.release.core_version, packs, rb.release.digest)
        systems = {k: SystemDef(s.system_id, s.core_type, s.source_systems, s.regulatory_scope, s.status)
                   for k, s in rb.systems.items()}
        return cls(pins, concepts, frozenset(rb.relationships), {k: frozenset(str(v) for v in vs) for k, vs in rb.vocabularies.items()},
                   by_system, systems, rb)


def build_ontology(config: Config) -> OntologyBundle | None:
    """The bundle named by `ontology.dir`, or None when the key is absent (the gate is then off).

    A relative dir is tried against the current directory, then against the repository root, so the
    local profile works from any working directory."""
    raw = config.get("ontology.dir")
    if not raw:
        return None
    root = Path(str(raw))
    if not root.is_absolute() and not root.is_dir():
        root = Path(__file__).resolve().parents[3] / root
    return OntologyBundle.load(
        root,
        list(config.get("ontology.packs") or []),
        allow_reference=bool(config.get("ontology.allow_reference_packs", False)),
        require_signed=bool(config.get("ontology.require_signed", False)),
    )
