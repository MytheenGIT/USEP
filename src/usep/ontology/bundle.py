"""Load the core and the pinned packs from disk (HLD 6.1: a tenant pins exact pack versions).

What is checked here, at load time, and fails closed with ConfigError:
- every pinned pack exists, has a valid manifest and needs a core version that is loaded;
- a pack marked reference_only is refused unless the config allows it (it shows shape, not content);
- an unsigned pack is refused when the config requires signatures (pack signing, C-07, is not built,
  so the default is to allow);
- two pinned packs at one level may not define the same concept (CC-16);
- a mapping must name a known concept, and its fields must be attributes of that concept.

What is NOT checked here: that a pack only adds and only tightens. That is pack CI
(ontology/tools/check_ontology.py). The loader trusts a pack that passed CI.

The digest covers the bytes of every file that defines the pinned ontology, so any edit changes it.
Line endings are normalised first so a Windows checkout and a Linux checkout agree.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from usep.core.config import Config
from usep.core.errors import ConfigError

LEVEL_ORDER = ("industry", "organization", "application", "project")   # least to most specific (HLD 6.1)
_FOLDER_FOR_LEVEL = {"industry": "industry", "organization": "org", "application": "app", "project": "project"}
_CARRIER_ROLES = frozenset({"carrier", "unmodelled", "evidence"})
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---- versions -----------------------------------------------------------------------------------
def _parse_version(text: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", text.strip())
    if not match:
        raise ConfigError(f"not a semantic version: {text!r}")
    return int(match[1]), int(match[2]), int(match[3])


def satisfies(version: str, spec: str) -> bool:
    """True if `version` meets every comparator in `spec`, for example ">=0.1.0 <1.0.0"."""
    have = _parse_version(version)
    for part in spec.split():
        match = re.fullmatch(r"(>=|<=|==|>|<)(\d+\.\d+\.\d+)", part)
        if not match:
            raise ConfigError(f"unsupported version range: {spec!r}")
        want = _parse_version(match[2])
        op = match[1]
        ok = {">=": have >= want, "<=": have <= want, "==": have == want, ">": have > want, "<": have < want}[op]
        if not ok:
            return False
    return True


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
def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _file_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


class OntologyBundle:
    def __init__(
        self,
        pins: OntologyPins,
        concepts: Mapping[str, ConceptDef],
        relationships: frozenset[str],
        vocabularies: Mapping[str, frozenset[str]],
        mappings: Mapping[str, SourceMapping],
        systems: Mapping[str, SystemDef] | None = None,
    ) -> None:
        self.pins = pins
        self.concepts = concepts
        self.relationships = relationships
        self.vocabularies = vocabularies
        self.mappings = mappings
        self.systems = systems or {}

    @classmethod
    def load(
        cls,
        root: str | Path,
        pack_ids: Sequence[str] = (),
        *,
        allow_reference: bool = False,
        require_signed: bool = False,
    ) -> "OntologyBundle":
        root = Path(root)
        core_dir = root / "core"
        if not (core_dir / "pack.yml").is_file():
            raise ConfigError(f"no core ontology at {core_dir}")
        core_manifest = _read_yaml(core_dir / "pack.yml")
        core_version = str(core_manifest.get("version", ""))
        _parse_version(core_version)
        if require_signed and not core_manifest.get("signed"):
            raise ConfigError("core ontology is not signed and ontology.require_signed is set")

        raw_concepts = _read_yaml(core_dir / "concepts.yml").get("concepts", [])
        raw_vocab = _read_yaml(core_dir / "vocabularies.yml")
        relationships = {r["id"] for r in _read_yaml(core_dir / "relationships.yml").get("relationships", [])}
        common = _read_yaml(core_dir / "common-attributes.yml")
        common_names = {a["name"] for a in common.get("node", {}).get("required", []) + common.get("node", {}).get("optional", [])}

        vocab: dict[str, set[str]] = {}
        for name, spec in raw_vocab.items():
            if isinstance(spec, Mapping) and isinstance(spec.get("values"), list):
                vocab[name] = {str(v["value"] if isinstance(v, Mapping) else v) for v in spec["values"]}

        defs: dict[str, tuple[str | None, list[dict[str, Any]]]] = {c["id"]: (None, c.get("attributes", [])) for c in raw_concepts}

        packs = cls._select_packs(root, pack_ids, core_version, allow_reference, require_signed)
        seen_terms: dict[tuple[str, str], str] = {}
        for pack in packs:
            level, pdir = pack["level"], pack["dir"]
            concepts_file = pdir / "concepts.yml"
            if concepts_file.is_file():
                added = _read_yaml(concepts_file)
                for c in added.get("concepts", []):
                    key = (level, c["id"])
                    if key in seen_terms:
                        raise ConfigError(f"concept {c['id']} defined twice at level {level} by {seen_terms[key]} and {pack['id']} (CC-16)")
                    seen_terms[key] = pack["id"]
                    if c["id"] in defs:
                        raise ConfigError(f"pack {pack['id']} redefines concept {c['id']}")
                    defs[c["id"]] = (c.get("subclass_of"), c.get("attributes", []))
                relationships.update(r["id"] for r in added.get("relationships", []))
            vocab_file = pdir / "vocabularies.yml"
            if vocab_file.is_file():
                added_vocab = _read_yaml(vocab_file)
                for name, spec in (added_vocab.get("extends") or {}).items():
                    vocab.setdefault(name, set()).update(str(v) for v in spec.get("add", []))
                for term in added_vocab.get("terms") or []:   # a pack's own vocabulary, for its own concepts
                    key = (level, "vocab", term["id"])
                    if key in seen_terms:
                        raise ConfigError(f"vocabulary {term['id']} defined twice at level {level} by {seen_terms[key]} and {pack['id']} (CC-16)")
                    if term["id"] in vocab:
                        raise ConfigError(f"pack {pack['id']} redefines vocabulary {term['id']}")
                    seen_terms[key] = pack["id"]
                    vocab[term["id"]] = {str(v) for v in term.get("values", [])}

        concepts = cls._resolve_concepts(defs)
        mappings = cls._load_mappings(packs, concepts, common_names)
        systems = cls._load_systems(packs, concepts, vocab)
        pins = OntologyPins(
            core_version=core_version,
            packs=tuple(PackPin(p["id"], p["level"], p["version"]) for p in packs),
            digest=cls._digest(root, packs),
        )
        return cls(pins, concepts, frozenset(relationships), {k: frozenset(v) for k, v in vocab.items()}, mappings, systems)

    # ---- helpers ------------------------------------------------------------------------------------
    @staticmethod
    def _select_packs(root: Path, pack_ids: Sequence[str], core_version: str, allow_reference: bool, require_signed: bool) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for level_folder in set(_FOLDER_FOR_LEVEL.values()):
            base = root / "packs" / level_folder
            if not base.is_dir():
                continue
            for pdir in sorted(p for p in base.iterdir() if p.is_dir() and (p / "pack.yml").is_file()):
                manifest = _read_yaml(pdir / "pack.yml")
                found[str(manifest.get("id"))] = {**manifest, "dir": pdir}
        chosen: list[dict[str, Any]] = []
        for pack_id in pack_ids:
            manifest = found.get(pack_id)
            if manifest is None:
                raise ConfigError(f"pinned pack not found: {pack_id}")
            if manifest.get("level") not in LEVEL_ORDER:
                raise ConfigError(f"pack {pack_id}: unknown level {manifest.get('level')!r}")
            _parse_version(str(manifest.get("version", "")))
            if not satisfies(core_version, str(manifest.get("requires_core", ""))):
                raise ConfigError(f"pack {pack_id} needs core {manifest.get('requires_core')}, loaded core is {core_version}")
            if manifest.get("reference_only") and not allow_reference:
                raise ConfigError(f"pack {pack_id} is reference_only; set ontology.allow_reference_packs to use it")
            if require_signed and not manifest.get("signed"):
                raise ConfigError(f"pack {pack_id} is not signed and ontology.require_signed is set")
            if any(c["id"] == pack_id for c in chosen):
                raise ConfigError(f"pack {pack_id} is pinned twice")
            chosen.append(manifest)
        chosen.sort(key=lambda m: LEVEL_ORDER.index(m["level"]))   # least specific first; stable within a level
        return chosen

    @staticmethod
    def _resolve_concepts(defs: Mapping[str, tuple[str | None, list[dict[str, Any]]]]) -> dict[str, ConceptDef]:
        resolved: dict[str, ConceptDef] = {}

        def build(cid: str, trail: tuple[str, ...] = ()) -> ConceptDef:
            if cid in resolved:
                return resolved[cid]
            if cid in trail or cid not in defs:
                raise ConfigError(f"concept {cid} has an unknown or circular parent")
            parent_id, raw_attrs = defs[cid]
            attrs: dict[str, AttributeDef] = dict(build(parent_id, (*trail, cid)).attributes) if parent_id else {}
            for a in raw_attrs:
                ref = a.get("values_ref")
                attrs[a["name"]] = AttributeDef(
                    name=a["name"], type=str(a.get("type", "string")), required=bool(a.get("required")),
                    multi=bool(a.get("multi")), values_ref=str(ref).split(".", 1)[-1] if ref else None,
                )
            resolved[cid] = ConceptDef(cid, parent_id, attrs)
            return resolved[cid]

        for cid in defs:
            build(cid)
        return resolved

    @staticmethod
    def _load_mappings(packs: Iterable[Mapping[str, Any]], concepts: Mapping[str, ConceptDef], common_names: set[str]) -> dict[str, SourceMapping]:
        out: dict[str, SourceMapping] = {}
        for pack in sorted(packs, key=lambda m: LEVEL_ORDER.index(m["level"]), reverse=True):   # most specific first
            mdir = pack["dir"] / "mappings"
            if not mdir.is_dir():
                continue
            for mfile in sorted(mdir.glob("*.yml")):
                data = _read_yaml(mfile)
                system = str(data.get("source_system", mfile.stem))
                sm = out.setdefault(system, SourceMapping(system))
                if data.get("on_unmapped"):
                    if data["on_unmapped"] not in ("quarantine", "evidence"):
                        raise ConfigError(f"{mfile.name}: on_unmapped must be quarantine or evidence")
                    sm.on_unmapped = data["on_unmapped"]
                for m in data.get("mappings", []):
                    entity = m.get("entity")
                    if entity is not None and entity not in concepts:
                        raise ConfigError(f"{mfile.name}: maps to unknown concept {entity}")
                    role = m.get("role")
                    if role is not None and role not in _CARRIER_ROLES:
                        raise ConfigError(f"{mfile.name}: unknown role {role}")
                    fields = {str(k): str(v) for k, v in (m.get("fields") or {}).items()}
                    if entity is not None:
                        allowed = set(concepts[entity].attributes) | common_names
                        for key in fields:
                            if key not in allowed:
                                raise ConfigError(f"{mfile.name}: field {key} is not an attribute of {entity}")
                    when = {str(k): tuple(str(x) for x in (v or [])) for k, v in (m.get("when") or {}).items()}
                    sm.entries.append(MappingEntry(
                        source_object=str(m["source_object"]), when=when, entity=entity,
                        relationship=m.get("relationship"), role=role, fields=fields, pack_level=pack["level"],
                    ))
        return out

    @staticmethod
    def _load_systems(packs: Iterable[Mapping[str, Any]], concepts: Mapping[str, ConceptDef], vocab: Mapping[str, set[str]]) -> dict[str, SystemDef]:
        out: dict[str, SystemDef] = {}
        scopes = vocab.get("regulatory_scope", set())
        for pack in packs:
            sfile = pack["dir"] / "systems.yml"
            if not sfile.is_file():
                continue
            for row in _read_yaml(sfile).get("systems", []):
                sid, core_type = str(row["system_id"]), str(row["core_type"])
                if core_type not in concepts:
                    raise ConfigError(f"{pack['id']}: system {sid} maps to unknown concept {core_type}")
                if sid in out:
                    raise ConfigError(f"system {sid} registered twice (by {pack['id']} and an earlier pack)")
                scope = tuple(str(x) for x in row.get("regulatory_scope") or [])
                unknown = [x for x in scope if x not in scopes]
                if unknown:
                    raise ConfigError(f"{pack['id']}: system {sid} names regulatory scope {unknown[0]}, which no pinned pack defines")
                out[sid] = SystemDef(sid, core_type, tuple(str(x) for x in row.get("source_systems") or []), scope, str(row.get("status", "")))
        return out

    @staticmethod
    def _digest(root: Path, packs: Iterable[Mapping[str, Any]]) -> str:
        files: list[Path] = []
        for sub in ("core", "templates"):
            files += [p for p in (root / sub).rglob("*") if p.is_file() and p.name != ".gitkeep"]
        files += [p for p in (root / "shapes").rglob("*.ttl")]
        for pack in packs:
            files += [p for p in pack["dir"].rglob("*") if p.is_file()]
        h = hashlib.sha256()
        for path in sorted(set(files), key=lambda p: p.relative_to(root).as_posix()):
            h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            h.update(_file_bytes(path) + b"\0")
        return h.hexdigest()


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
