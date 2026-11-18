"""Ontology checks: a first, local version of pack CI (C-07).

Source rules: HLD 6.1 (additive only, policies only tighten, same-level conflicts fail), HLD 6.2 (shape and
template tests), LLD 2.3 Table 3 (any failed shape, template or conflict test blocks the merge), LLD 4 (traversal
limits), LLD 13 CC-16 and CC-17. It is not the production service: the signing step and the registry publish are not here.

Run from the repository root:  python ontology/tools/check_ontology.py
Exit code 0 when every check passes, 1 otherwise.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]          # ontology/
LEVELS = ("industry", "org", "app", "project")
LEVEL_NAME = {"industry": "industry", "org": "organization", "app": "application", "project": "project"}
FORBIDDEN_KEYS = {"remove", "delete", "redefine", "override", "replace", "rename"}
ALLOWED_POLICY_EFFECTS = {"deny", "require_approval", "restrict_to_owners"}   # nothing that grants access
CORE_CONCEPTS = {"Capability", "Application", "Service", "API", "DataAsset", "Team", "Person", "Requirement",
                 "Change", "Incident", "Decision", "Policy", "Control", "Environment", "Release", "Test"}
CORE_RELATIONSHIPS = {"owns", "depends_on", "exposes", "consumes", "realizes", "implements", "tests",
                      "deployed_to", "governed_by", "caused_by", "decided_in", "supersedes"}
MAX_DEPTH, MAX_FANOUT = 3, 200                      # config.context.max_depth, config.context.fanout_cap (LLD 4)
RUNTIME_PARAMS = {"reached_ids", "fanout_cap"}      # supplied by the context engine, not the caller


def load(path: Path):
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def fail(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def expect(self, cond: bool, where: str, msg: str) -> None:
        if not cond:
            self.fail(where, msg)


def walk_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}/{k}", k
            yield from walk_keys(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_keys(v, f"{path}[{i}]")


# ---------------------------------------------------------------- core
def check_core(rep: Report):
    core = ROOT / "core"
    manifest = load(core / "pack.yml")
    concepts = load(core / "concepts.yml")
    rels = load(core / "relationships.yml")
    vocab = load(core / "vocabularies.yml")
    domains = load(core / "domains.yml")
    common = load(core / "common-attributes.yml")
    hooks = load(core / "policy-hooks.yml")
    policies = load(core / "policies.yml")

    ids = [c["id"] for c in concepts["concepts"]]
    rep.expect(len(ids) == len(set(ids)), "core/concepts", "duplicate concept id")
    rep.expect(set(ids) == CORE_CONCEPTS, "core/concepts",
               f"concept set differs from HLD 6 Table 9: {set(ids) ^ CORE_CONCEPTS}")
    domain_ids = {d["id"] for d in domains["domains"]}
    rep.expect(len(domain_ids) == 7, "core/domains", "expected seven semantic domains (HLD 6 Table 9)")
    for c in concepts["concepts"]:
        rep.expect(c["domain"] in domain_ids, f"core/concepts/{c['id']}", f"unknown domain {c['domain']}")
        for a in c.get("attributes", []):
            ref = a.get("values_ref")
            if ref:
                rep.expect(ref.split(".", 1)[-1] in vocab, f"core/concepts/{c['id']}.{a['name']}",
                           f"values_ref {ref} not in vocabularies")
    rel_ids = [r["id"] for r in rels["relationships"]]
    rep.expect(len(rel_ids) == len(set(rel_ids)), "core/relationships", "duplicate relationship id")
    rep.expect(set(rel_ids) == CORE_RELATIONSHIPS, "core/relationships",
               f"relationship set differs from HLD 6 Table 9: {set(rel_ids) ^ CORE_RELATIONSHIPS}")
    for r in rels["relationships"]:
        for end in ("from", "to"):
            for t in r[end]:
                rep.expect(t in CORE_CONCEPTS, f"core/relationships/{r['id']}", f"{end} type {t} is not a core concept")
    attrs = {a["name"] for sect in ("required", "optional") for a in common["node"][sect]}
    attrs |= {a["name"] for c in concepts["concepts"] for a in c.get("attributes", [])}
    for h in hooks["hooks"]:
        rep.expect(h["attribute"] in attrs, f"core/policy-hooks/{h['id']}", f"attribute {h['attribute']} is not defined")
    rep.expect(policies["default_decision"] == "deny", "core/policies", "default decision must be deny (fail closed)")
    rep.expect(policies["combine"] == "deny_overrides", "core/policies", "combine rule must be deny_overrides")
    rep.expect(manifest["additive_only"] is True, "core/pack.yml", "additive_only must be true")
    for rel in manifest["shapes"]:
        rep.expect((core / rel).resolve().exists(), "core/pack.yml", f"shape file missing: {rel}")
    rep.expect(manifest["signed"] is False or manifest.get("signature_ref"), "core/pack.yml", "signed pack needs signature_ref")
    return {"concepts": concepts, "rels": rels, "vocab": vocab, "attrs": attrs, "policies": policies,
            "concept_ids": CORE_CONCEPTS, "rel_ids": CORE_RELATIONSHIPS}


# ---------------------------------------------------------------- packs
def semver_ok(v: str) -> bool:
    return bool(re.fullmatch(r"\d+\.\d+\.\d+", v))


def check_pack(rep: Report, level: str, pack_dir: Path, core: dict, seen_terms: dict):
    where = f"packs/{level}/{pack_dir.name}"
    mf_path = pack_dir / "pack.yml"
    rep.expect(mf_path.exists(), where, "pack.yml missing")
    if not mf_path.exists():
        return
    mf = load(mf_path)
    rep.expect(mf.get("level") == LEVEL_NAME[level], where, f"manifest level {mf.get('level')} does not match folder {level}")
    rep.expect(mf.get("id", "").startswith(("industry.", "org.", "app.", "project.")), where, "pack id needs a level prefix")
    rep.expect(semver_ok(mf.get("version", "")), where, "version must be semantic (major.minor.patch)")
    rep.expect(mf.get("additive_only") is True, where, "additive_only must be true")
    rep.expect(bool(mf.get("requires_core")), where, "requires_core is missing")
    rep.expect(mf.get("signed") is False or bool(mf.get("signature_ref")), where, "signed pack needs signature_ref")
    rep.expect(mf.get("owner_role"), where, "owner_role is missing")

    for yml in sorted(pack_dir.rglob("*.yml")):
        data = load(yml)
        for p, k in walk_keys(data):
            rep.expect(k not in FORBIDDEN_KEYS, f"{where}/{yml.relative_to(pack_dir)}",
                       f"key '{k}' at {p}: packs add, they never delete or redefine (ADR-08)")

    local_concepts: set[str] = set()
    local_rels: set[str] = set()
    cfile = pack_dir / "concepts.yml"
    if cfile.exists():
        data = load(cfile)
        for c in data.get("concepts", []):
            cid = c["id"]
            rep.expect(cid not in core["concept_ids"], where, f"concept {cid} redefines a core concept")
            rep.expect(c.get("subclass_of") in core["concept_ids"] | local_concepts, where,
                       f"concept {cid} must extend a known concept (subclass_of {c.get('subclass_of')})")
            key = ("concept", cid)
            rep.expect(key not in seen_terms, where, f"{cid} already defined at the same level by {seen_terms.get(key)} (CC-16)")
            seen_terms[key] = pack_dir.name
            local_concepts.add(cid)
        for r in data.get("relationships", []):
            rep.expect(r["id"] not in core["rel_ids"], where, f"relationship {r['id']} redefines a core relationship")
            local_rels.add(r["id"])
    vfile = pack_dir / "vocabularies.yml"
    if vfile.exists():
        data = load(vfile)
        for name, spec in data.get("extends", {}).items():
            rep.expect(name in core["vocab"] or name == "regulatory_scope", where, f"extends unknown vocabulary {name}")
            rep.expect(set(spec) <= {"add"}, where, f"vocabulary {name}: only 'add' is allowed")
            for term in spec.get("add", []):
                key = ("vocab", name, term)
                rep.expect(key not in seen_terms, where, f"{term} already added at the same level by {seen_terms.get(key)} (CC-16)")
                seen_terms[key] = pack_dir.name
    pfile = pack_dir / "policies.yml"
    if pfile.exists():
        data = load(pfile)
        core_pol = {p["id"] for p in core["policies"]["policies"]}
        for pol in data.get("policies", []):
            rep.expect(pol["effect"] in ALLOWED_POLICY_EFFECTS, where,
                       f"policy {pol['id']}: effect {pol['effect']} could loosen access (policies only tighten)")
            rep.expect(pol["id"] not in core_pol, where, f"policy {pol['id']} reuses a core policy id")
            rep.expect(not pol["id"].startswith("core."), where, f"policy {pol['id']} uses the reserved core. prefix")
            if pol["effect"] == "require_approval":
                rep.expect(pol.get("approvals", {}).get("min_tier", 0) >= 1, where, f"policy {pol['id']}: approval tier missing")
    prfile = pack_dir / "precedence.yml"
    if prfile.exists():
        data = load(prfile)
        for attr in data.get("attributes", {}):
            rep.expect(attr in core["attrs"], where, f"precedence names unknown attribute {attr}")
    for mfile in sorted((pack_dir / "mappings").glob("*.yml")) if (pack_dir / "mappings").exists() else []:
        data = load(mfile)
        for m in data.get("mappings", []):
            ent = m.get("entity", "__none__")
            if ent not in ("__none__", None):
                rep.expect(ent in core["concept_ids"] | local_concepts, f"{where}/{mfile.name}", f"maps to unknown entity {ent}")
            rel = m.get("relationship")
            if rel:
                rep.expect(rel in core["rel_ids"] | local_rels, f"{where}/{mfile.name}", f"maps to unknown relationship {rel}")
                for end in ("from_entity", "to_entity"):
                    rep.expect(m[end] in core["concept_ids"] | local_concepts, f"{where}/{mfile.name}", f"unknown {end} {m[end]}")
    wfile = pack_dir / "workflow.yml"
    if wfile.exists():
        data = load(wfile)
        states = set(core["vocab"]["change_state"]["values"])
        for row in data.get("issue_workflow", []):
            rep.expect(row["change_state"] in states, where, f"workflow maps to unknown change_state {row['change_state']}")
        req = set(core["vocab"]["requirement_status"]["values"])
        for row in data.get("requirement_status", []):
            rep.expect(row["status"] in req, where, f"workflow maps to unknown requirement status {row['status']}")
    return mf


def check_packs(rep: Report, core: dict):
    for level in LEVELS:
        seen: dict = {}
        for pack_dir in sorted(p for p in (ROOT / "packs" / level).iterdir() if p.is_dir()):
            check_pack(rep, level, pack_dir, core, seen)


# ---------------------------------------------------------------- templates
def check_templates(rep: Report, core: dict):
    labels = core["concept_ids"] | {"Entity"}
    for path in sorted((ROOT / "templates").glob("*.yml")):
        t = load(path)
        where = f"templates/{path.name}"
        rep.expect(t["name"] == path.stem, where, "file name must equal template name")
        rep.expect(isinstance(t.get("version"), str), where, "version must be a string")
        lim = t.get("limits", {})
        rep.expect(lim.get("max_depth", 99) <= MAX_DEPTH, where, f"max_depth above {MAX_DEPTH}")
        rep.expect(lim.get("fanout_cap", 9999) <= MAX_FANOUT, where, f"fanout_cap above {MAX_FANOUT}")
        declared = {p["name"] for p in t.get("parameters", [])}
        rep.expect("tenant_id" in declared, where, "tenant_id must be a declared parameter (ADR-10)")
        for p in t.get("parameters", []):
            if p["name"] == "depth":
                rep.expect(p.get("max", 99) <= MAX_DEPTH, where, "depth parameter max above limit")
        rep.expect("{{access_predicate}}" in t.get("access", ""), where, "access note must name {{access_predicate}} (ADR-06)")
        for step in t["steps"]:
            sw = f"{where}#{step['id']}"
            cy = step["cypher"]
            used = set(re.findall(r"\$([A-Za-z_]+)", cy))
            rep.expect(used <= declared | RUNTIME_PARAMS, sw, f"undeclared parameters {used - declared - RUNTIME_PARAMS}")
            rep.expect("$tenant_id" in cy, sw, "query does not filter on tenant_id")
            rep.expect("{{access_predicate}}" in cy, sw, "query does not apply the access predicate inside the match (ADR-06)")
            rep.expect(re.search(r"\bLIMIT\b", cy) is not None, sw, "query has no LIMIT")
            for n in re.findall(r"\*\d+\.\.(\d+)", cy):
                rep.expect(int(n) <= MAX_DEPTH, sw, f"variable-length path deeper than {MAX_DEPTH}")
            for lab in re.findall(r"\(\w*:([A-Za-z]+)", cy):
                rep.expect(lab in labels, sw, f"unknown node label {lab}")
            for grp in re.findall(r"\[\w*:([a-z_|]+)", cy):
                for rel in grp.split("|"):
                    rep.expect(rel in core["rel_ids"], sw, f"unknown relationship type {rel}")


# ---------------------------------------------------------------- shapes and fixtures
def check_shapes(rep: Report, core: dict):
    from rdflib import Graph, Namespace, RDF, URIRef
    SH = Namespace("http://www.w3.org/ns/shacl#")
    USEP = Namespace("https://usep.invalid/ontology/core#")
    g = Graph()
    for ttl in sorted((ROOT / "shapes").rglob("*.ttl")):
        try:
            g.parse(ttl, format="turtle")
        except Exception as exc:  # noqa: BLE001
            rep.fail(f"shapes/{ttl.name}", f"does not parse: {exc}")
    targeted = {str(o) for o in g.objects(None, SH.targetClass)}
    for cid in core["concept_ids"]:
        rep.expect(str(USEP[cid]) in targeted, "shapes", f"no shape targets core concept {cid}")
    subj = {str(o) for o in g.objects(None, SH.targetSubjectsOf)}
    obj = {str(o) for o in g.objects(None, SH.targetObjectsOf)}
    for rid in core["rel_ids"]:
        rep.expect(str(USEP[rid]) in subj, "shapes", f"no start-type shape for relationship {rid}")
        rep.expect(str(USEP[rid]) in obj, "shapes", f"no end-type shape for relationship {rid}")
    return g


def conforms(data_graph, shapes_graph) -> tuple[bool, str]:
    from pyshacl import validate
    ok, _, text = validate(data_graph, shacl_graph=shapes_graph, inference="none", advanced=False)
    return ok, text


def check_fixture(rep: Report, shapes):
    from rdflib import Graph
    fx = ROOT / "tests" / "fixtures" / "valid-minimal.ttl"
    data = Graph().parse(fx, format="turtle")
    ok, text = conforms(data, shapes)
    rep.expect(ok, "tests/fixtures/valid-minimal.ttl", f"valid fixture does not conform:\n{text}")


def run() -> int:
    rep = Report()
    core = check_core(rep)
    check_packs(rep, core)
    check_templates(rep, core)
    shapes = check_shapes(rep, core)
    check_fixture(rep, shapes)
    if rep.errors:
        print(f"FAIL: {len(rep.errors)} problem(s)")
        for e in rep.errors:
            print("  -", e)
        return 1
    print("OK: core, packs, templates, shapes and fixture all pass")
    return 0


if __name__ == "__main__":
    sys.exit(run())
