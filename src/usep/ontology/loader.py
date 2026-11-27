"""Ontology loader: reads the core and the pinned packs from a checkout of ontology/ and fails closed.

Fail closed means a problem with the core or any pinned pack raises OntologyLoadError listing every problem; no
partial ontology is ever returned (HLD 8; ADR-14). Packs add and never replace (ADR-08), policies only tighten
(CC-17), one definition per term per level (CC-16), a pack that needs another core version is refused.

This is the local stand-in for the registry client (C-06). It reads Git; it does not verify signatures yet,
because pack CI signing (C-07) does not exist. Until it does, a signed pack is refused unless it has a signature_ref
and an unsigned pack is only accepted when `allow_unsigned` is true (default true while nothing is signed).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

from usep.core.errors import OntologyLoadError
from usep.ontology.model import (
    LEVEL_ORDER, Attribute, Concept, Mapping_, OntologyBundle, OntologyRelease, PackInfo, Policy, Relationship,
    Template,
)
from usep.ontology.release import digest_files

FORBIDDEN_KEYS = {"remove", "delete", "redefine", "override", "replace", "rename"}
ALLOWED_POLICY_EFFECTS = {"deny", "require_approval", "restrict_to_owners"}
MAX_DEPTH, MAX_FANOUT = 3, 200
PACK_DIRS = {"industry": "industry", "organization": "org", "application": "app", "project": "project"}
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class PackPin:
    """A tenant's pin: exact pack id and version (rule 5, pin and finish)."""
    id: str
    version: str

    @classmethod
    def parse(cls, text: str) -> "PackPin":
        pid, sep, ver = text.partition("@")
        if not sep or not pid or not _SEMVER.match(ver):
            raise OntologyLoadError([f"pin '{text}' must look like <pack-id>@<major.minor.patch>"])
        return cls(pid, ver)


def _read(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _semver(v: str) -> tuple[int, int, int]:
    m = _SEMVER.match(v)
    if not m:
        raise ValueError(v)
    return int(m[1]), int(m[2]), int(m[3])


def satisfies(version: str, spec: str | None) -> bool:
    """Space-separated comparators such as '>=0.1.0 <1.0.0'. An empty spec accepts nothing: packs must say."""
    if not spec:
        return False
    ops = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
           "<": lambda a, b: a < b, "==": lambda a, b: a == b}
    v = _semver(version)
    for tok in spec.split():
        m = re.match(r"^(>=|<=|==|>|<)(\d+\.\d+\.\d+)$", tok)
        if not m or not ops[m[1]](v, _semver(m[2])):
            return False
    return True


def _forbidden(obj: Any, path: str = "") -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS:
                yield f"{path}/{k}"
            yield from _forbidden(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _forbidden(v, f"{path}[{i}]")


class _Loader:
    def __init__(self, root: Path, pins: Sequence[PackPin], allow_reference_only: bool, allow_unsigned: bool,
                 supported_core: str | None):
        self.root = root.resolve()
        self.pins = list(pins)
        self.allow_reference_only = allow_reference_only
        self.allow_unsigned = allow_unsigned
        self.supported_core = supported_core
        self.problems: list[str] = []
        self.files: list[Path] = []

    def bad(self, where: str, msg: str) -> None:
        self.problems.append(f"{where}: {msg}")

    def read(self, path: Path, where: str) -> Any:
        if not path.is_file():
            self.bad(where, f"file missing: {path.relative_to(self.root).as_posix()}")
            return {}
        self.files.append(path)
        data = _read(path)
        for hit in _forbidden(data):
            self.bad(where, f"forbidden key at {hit}: packs add, they never remove or redefine (ADR-08)")
        return data

    # ------------------------------------------------------------ manifests
    def manifest(self, pack_dir: Path, where: str) -> dict:
        mf = self.read(pack_dir / "pack.yml", where)
        if mf.get("additive_only") is not True:
            self.bad(where, "additive_only must be true")
        if mf.get("signed") is True and not mf.get("signature_ref"):
            self.bad(where, "signed pack has no signature_ref")
        if mf.get("signed") is not True and not self.allow_unsigned:
            self.bad(where, "pack is unsigned and unsigned packs are not allowed")
        if mf.get("status") not in {"draft", "candidate", "published"}:
            self.bad(where, f"unknown status {mf.get('status')!r}")
        return mf

    def info(self, mf: dict) -> PackInfo:
        return PackInfo(id=mf.get("id", "?"), level=mf.get("level", "?"), version=str(mf.get("version", "")),
                        status=mf.get("status", "?"), signed=mf.get("signed") is True,
                        reference_only=mf.get("reference_only") is True)

    def vocab_values(self, items: list) -> tuple:
        return tuple(i["value"] if isinstance(i, dict) else i for i in items)

    # ------------------------------------------------------------ core
    def load_core(self):
        core_dir = self.root / "core"
        mf = self.manifest(core_dir, "core")
        if self.supported_core and not satisfies(str(mf.get("version", "")), self.supported_core):
            self.bad("core", f"version {mf.get('version')} outside supported range {self.supported_core}")
        files = mf.get("files", {})
        get = lambda k: self.read(core_dir / files.get(k, f"{k}.yml"), f"core/{k}")   # noqa: E731
        common, vocab_raw = get("common_attributes"), get("vocabularies")
        domains, concepts_raw = get("domains"), get("concepts")
        rels_raw, policies_raw = get("relationships"), get("policies")
        get("policy_hooks")
        for rel in mf.get("shapes", []):
            if (core_dir / rel).is_file():
                self.files.append((core_dir / rel).resolve())
            else:
                self.bad("core", f"shape file missing: {rel}")
        return mf, common, vocab_raw, domains, concepts_raw, rels_raw, policies_raw

    def templates(self, mf: dict) -> dict[str, Template]:
        out: dict[str, Template] = {}
        tdir = (self.root / "core" / mf.get("templates_dir", "../templates")).resolve()
        for path in sorted(tdir.glob("*.yml")):
            t = self.read(path, f"templates/{path.name}")
            name, lim = t.get("name", path.stem), t.get("limits", {})
            depth, fan = lim.get("max_depth", 99), lim.get("fanout_cap", 10**9)
            steps = tuple(s.get("cypher", "") for s in t.get("steps", []))
            where = f"templates/{path.name}"
            if depth > MAX_DEPTH or fan > MAX_FANOUT:
                self.bad(where, f"limits exceed depth {MAX_DEPTH} / fan-out {MAX_FANOUT}")
            for i, q in enumerate(steps):
                if "tenant_id" not in q:
                    self.bad(where, f"step {i} does not filter on tenant_id (ADR-10)")
                if "{{access_predicate}}" not in q:
                    self.bad(where, f"step {i} has no access predicate inside the match (ADR-06)")
                if not re.search(r"\bLIMIT\b", q):
                    self.bad(where, f"step {i} has no LIMIT")
            out[name] = Template(name, depth, fan, steps)
        return out


def load_ontology(root: str | Path, pins: Sequence[PackPin | str] = (), *, allow_reference_only: bool = False,
                  allow_unsigned: bool = True, supported_core: str | None = None) -> OntologyBundle:
    """Load the core and exactly the pinned packs. Raises OntologyLoadError with every problem found."""
    L = _Loader(Path(root), [p if isinstance(p, PackPin) else PackPin.parse(p) for p in pins],
                allow_reference_only, allow_unsigned, supported_core)
    mf, common, vocab_raw, domains, concepts_raw, rels_raw, policies_raw = L.load_core()
    core_version = str(mf.get("version", ""))
    core_info = L.info(mf)

    # ---- vocabularies: the core's, plus values a pack adds (add only)
    vocab: dict[str, tuple] = {}
    for name, body in vocab_raw.items():
        if isinstance(body, dict) and "values" in body:
            vocab[name] = L.vocab_values(body["values"])
    domain_ids = tuple(d["id"] for d in domains.get("domains", []))
    vocab["domains"] = domain_ids

    # ---- find and check pinned packs before reading their content
    index: dict[str, tuple[Path, dict]] = {}
    for level_dir in PACK_DIRS.values():
        base = L.root / "packs" / level_dir
        for pdir in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
            if (pdir / "pack.yml").is_file():
                data = _read(pdir / "pack.yml")
                index.setdefault(data.get("id", pdir.name), (pdir, data))
    pinned: list[tuple[Path, dict]] = []
    seen_ids: set[str] = set()
    for pin in L.pins:
        where = f"pack {pin.id}"
        if pin.id in seen_ids:
            L.bad(where, "pinned twice")
            continue
        seen_ids.add(pin.id)
        if pin.id not in index:
            L.bad(where, "pinned pack not found (fail closed)")
            continue
        pdir, raw = index[pin.id]
        if str(raw.get("version")) != pin.version:
            L.bad(where, f"pin {pin.version} but checkout holds {raw.get('version')}")
            continue
        pmf = L.manifest(pdir, where)
        if not satisfies(core_version, pmf.get("requires_core")):
            L.bad(where, f"requires core {pmf.get('requires_core')!r} but core is {core_version}")
        if pmf.get("reference_only") and not L.allow_reference_only:
            L.bad(where, "reference-only pack (placeholder content) cannot be loaded here")
        if raw.get("level") not in PACK_DIRS or PACK_DIRS[raw["level"]] != pdir.parent.name:
            L.bad(where, f"level {raw.get('level')!r} does not match folder {pdir.parent.name!r}")
        pinned.append((pdir, pmf))
    pinned.sort(key=lambda x: (LEVEL_ORDER.index(x[1]["level"]) if x[1].get("level") in LEVEL_ORDER else 99, x[1].get("id", "")))

    packs_data = []
    for pdir, pmf in pinned:
        where, fs = f"pack {pmf.get('id')}", pmf.get("files", {})
        entry: dict[str, Any] = {"mf": pmf, "dir": pdir}
        for key in ("concepts", "vocabularies", "policies", "precedence", "glossary", "systems", "workflow",
                    "approval_matrix", "definition_of_done"):
            if key in fs:
                entry[key] = L.read(pdir / fs[key], where)
        entry["mappings"] = [L.read(pdir / m, where) for m in fs.get("mappings", [])]
        packs_data.append(entry)
        for name, ext in (entry.get("vocabularies", {}).get("extends") or {}).items():
            base_vals = vocab.get(name, ())
            vocab[name] = base_vals + tuple(v for v in ext.get("add", []) if v not in base_vals)

    # ---- attributes
    def attrs(items: list[dict], where: str) -> tuple[Attribute, ...]:
        out = []
        for a in items or []:
            ref = a.get("values_ref")
            values = None
            if ref:
                values = vocab.get(ref.split(".", 1)[-1])
                if values is None:
                    L.bad(where, f"attribute {a['name']}: values_ref {ref} not found")
            out.append(Attribute(a["name"], a.get("type", "string"), bool(a.get("required")), bool(a.get("multi")),
                                 values))
        return tuple(out)

    common_req = attrs(common.get("node", {}).get("required"), "core/common-attributes")
    common_opt = attrs(common.get("node", {}).get("optional"), "core/common-attributes")

    # ---- concepts and relationships (core first, then packs from least to most specific)
    concepts: dict[str, Concept] = {}
    for c in concepts_raw.get("concepts", []):
        if c["id"] in concepts:
            L.bad("core/concepts", f"duplicate concept {c['id']}")
        concepts[c["id"]] = Concept(c["id"], c.get("domain"), "core", None, bool(c.get("role_only")),
                                    attrs(c.get("attributes"), f"core/concepts/{c['id']}"))
    rels: dict[str, Relationship] = {}
    for r in rels_raw.get("relationships", []):
        rels[r["id"]] = Relationship(r["id"], tuple(r["from"]), tuple(r["to"]))
    policies = [Policy(p["id"], p["effect"], "core", p.get("when", {}), p.get("approvals", {}))
                for p in policies_raw.get("policies", [])]

    owner: dict[str, str] = {k: "core" for k in concepts}
    for e in packs_data:
        pmf, where = e["mf"], f"pack {e['mf'].get('id')}"
        level = pmf["level"]
        for c in (e.get("concepts") or {}).get("concepts", []):
            cid = c["id"]
            if cid in concepts:
                L.bad(where, f"concept {cid} already defined by {owner[cid]} (CC-16; additive only)")
                continue
            parent = c.get("subclass_of")
            if parent and parent not in concepts:
                L.bad(where, f"{cid}: subclass_of {parent} is unknown")
            parent_domain = concepts[parent].domain if parent in concepts else None
            concepts[cid] = Concept(cid, c.get("domain", parent_domain), level, parent, False,
                                    attrs(c.get("attributes"), f"{where}/{cid}"))
            owner[cid] = pmf["id"]
        for r in (e.get("concepts") or {}).get("relationships", []) or []:
            if r["id"] in rels:
                L.bad(where, f"relationship {r['id']} already defined (additive only)")
                continue
            rels[r["id"]] = Relationship(r["id"], tuple(r["from"]), tuple(r["to"]), level)
        for p in (e.get("policies") or {}).get("policies", []):
            if p.get("effect") not in ALLOWED_POLICY_EFFECTS:
                L.bad(where, f"policy {p.get('id')} has effect {p.get('effect')!r}: policies only tighten (CC-17)")
                continue
            policies.append(Policy(p["id"], p["effect"], level, p.get("when", {}), p.get("approvals", {})))

    for r in rels.values():
        for t in (*r.from_types, *r.to_types):
            if t not in concepts:
                L.bad(f"relationship {r.id}", f"endpoint type {t} is not a concept")

    # ---- mappings, precedence, glossary
    mappings: list[Mapping_] = []
    precedence: dict[str, Any] = {}
    glossary: dict[str, str] = {}
    workflow: dict[str, Any] = {}
    for e in packs_data:
        pid, where = e["mf"]["id"], f"pack {e['mf']['id']}"
        for m in e["mappings"]:
            sysname = m.get("source_system")
            for row in m.get("mappings", []):
                ent, rel = row.get("entity"), row.get("relationship")
                evidence_only = "entity" in row and ent is None and not rel     # text kept as evidence, no entity
                if not evidence_only and bool(ent) == bool(rel):
                    L.bad(where, f"{sysname}/{row.get('source_object')}: needs exactly one of entity or relationship")
                    continue
                if ent and ent not in concepts:
                    L.bad(where, f"{sysname}/{row['source_object']}: entity {ent} is not a concept")
                if rel:
                    if rel not in rels:
                        L.bad(where, f"{sysname}/{row['source_object']}: relationship {rel} is unknown")
                    for end in ("from_entity", "to_entity"):
                        if row.get(end) not in concepts:
                            L.bad(where, f"{sysname}/{row['source_object']}: {end} {row.get(end)} is not a concept")
                mappings.append(Mapping_(
                    pid, sysname, row["source_object"],
                    {k: tuple(v) for k, v in (row.get("when") or {}).items()},
                    ent, rel, row.get("from_entity"), row.get("to_entity"), dict(row.get("fields") or {}),
                    evidence_only))
        if "workflow" in e:
            workflow.update(e["workflow"])                               # a more specific pack wins
        if "precedence" in e:
            precedence.update(e["precedence"].get("attributes", {}))     # a more specific pack wins (HLD 6.1)
        for t in (e.get("glossary") or {}).get("terms", []):
            if t.get("maps_to") in concepts and t.get("status") != "placeholder":
                glossary[t["term"]] = t["maps_to"]

    templates = L.templates(mf)

    if L.problems:
        raise OntologyLoadError(L.problems)

    release = OntologyRelease(
        core_version=core_version,
        packs=(core_info, *(L.info(pmf) for _, pmf in pinned)),
        digest=digest_files(L.root, L.files),
    )
    return OntologyBundle(release, domain_ids, common_req, common_opt, vocab, concepts, rels, tuple(policies),
                          templates, tuple(mappings), precedence, glossary, workflow)
