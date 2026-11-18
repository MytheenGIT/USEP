"""Tests for the ontology checks. Each rule is shown to pass on good input and to fail on bad input.

Rules covered: HLD 6.1 (additive only, policies only tighten, same-level conflicts fail), HLD 6 Table 9 constraints
(exactly one owning team, mandatory attributes, allowed values, temporal validity, person by role only),
LLD 4 traversal limits, ADR-06 (access inside the match) and ADR-10 (tenant in every query).
"""
import copy
import sys
from pathlib import Path

import pytest
import yaml
from rdflib import Graph, Literal, Namespace, RDF, URIRef, XSD

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check_ontology as co  # noqa: E402

USEP = Namespace("https://usep.invalid/ontology/core#")
EX = Namespace("https://usep.invalid/synthetic#")
FIXTURE = ROOT / "tests" / "fixtures" / "valid-minimal.ttl"


@pytest.fixture(scope="module")
def report_core():
    rep = co.Report()
    core = co.check_core(rep)
    return rep, core


@pytest.fixture(scope="module")
def shapes(report_core):
    rep, core = report_core
    return co.check_shapes(co.Report(), core)


@pytest.fixture()
def data():
    return Graph().parse(FIXTURE, format="turtle")


# ---- the repository as it stands ----
def test_repository_passes_all_checks():
    assert co.run() == 0


# ---- shapes: good data and bad data ----
def test_valid_fixture_conforms(data, shapes):
    ok, text = co.conforms(data, shapes)
    assert ok, text


def test_service_with_no_owner_fails(data, shapes):
    data.remove((EX["team-payments"], USEP.owns, EX["svc-checkout"]))
    ok, text = co.conforms(data, shapes)
    assert not ok and "exactly one owning Team" in text


def test_service_with_two_owners_fails(data, shapes):
    second = EX["team-other"]
    data.add((second, RDF.type, USEP.Team))
    for p, v in data.predicate_objects(EX["team-payments"]):
        if p != USEP.owns and p != RDF.type:
            data.add((second, p, v))
    data.set((second, USEP.entity_id, Literal("01930000-0000-7000-8000-0000000000a2")))
    data.add((second, USEP.owns, EX["svc-checkout"]))
    ok, text = co.conforms(data, shapes)
    assert not ok and "exactly one owning Team" in text


def test_person_with_email_fails(data, shapes):
    data.add((EX["role-approver"], USEP.email, Literal("someone@example.invalid")))
    ok, text = co.conforms(data, shapes)
    assert not ok and "role only" in text


def test_unknown_domain_fails(data, shapes):
    data.set((EX["svc-checkout"], USEP.domain, Literal("finance")))
    ok, text = co.conforms(data, shapes)
    assert not ok and "seven semantic domains" in text


def test_sensitivity_out_of_range_fails(data, shapes):
    data.set((EX["svc-checkout"], USEP.sensitivity, Literal(7, datatype=XSD.integer)))
    ok, _ = co.conforms(data, shapes)
    assert not ok


def test_tenant_id_must_be_uuid_v7(data, shapes):
    data.set((EX["svc-checkout"], USEP.tenant_id, Literal("not-a-uuid")))
    ok, text = co.conforms(data, shapes)
    assert not ok and "UUID v7" in text


def test_valid_to_before_valid_from_fails(data, shapes):
    data.set((EX["svc-checkout"], USEP.valid_to,
              Literal("2026-10-01T00:00:00.000Z", datatype=XSD.dateTime)))
    ok, text = co.conforms(data, shapes)
    assert not ok and "valid_from" in text


def test_missing_mandatory_attribute_fails(data, shapes):
    data.remove((EX["svc-checkout"], USEP.source_id, None))
    ok, _ = co.conforms(data, shapes)
    assert not ok


def test_bad_enum_value_fails(data, shapes):
    data.set((EX["svc-checkout"], USEP.criticality, Literal("tier_9")))
    ok, _ = co.conforms(data, shapes)
    assert not ok


def test_relationship_with_wrong_endpoint_type_fails(data, shapes):
    data.add((EX["svc-checkout"], USEP.owns, EX["team-payments"]))        # a Service cannot own a Team
    ok, text = co.conforms(data, shapes)
    assert not ok and "owns" in text


def test_consumes_pointing_at_a_team_fails(data, shapes):
    data.add((EX["svc-checkout"], USEP.consumes, EX["team-payments"]))
    ok, _ = co.conforms(data, shapes)
    assert not ok


# ---- packs: build a throwaway pack and check it ----
def write_pack(tmp_path, level="org", manifest=None, **files):
    d = tmp_path / "p"
    d.mkdir()
    mf = {"id": f"{level}.test", "level": co.LEVEL_NAME[level], "version": "0.1.0", "status": "draft", "signed": False,
          "owner_role": "x", "requires_core": ">=0.1.0", "additive_only": True}
    mf.update(manifest or {})
    (d / "pack.yml").write_text(yaml.safe_dump(mf), encoding="utf-8")
    for name, content in files.items():
        (d / f"{name}.yml").write_text(yaml.safe_dump(content), encoding="utf-8")
    return d


def run_pack(tmp_path, level="org", seen=None, **kw):
    rep = co.Report()
    _, core = rep, co.check_core(co.Report())
    co.check_pack(rep, level, write_pack(tmp_path, level, **kw), core, seen if seen is not None else {})
    return rep.errors


def test_clean_pack_passes(tmp_path):
    assert run_pack(tmp_path, concepts={"concepts": [{"id": "Squad", "subclass_of": "Team"}]}) == []


def test_pack_redefining_core_concept_fails(tmp_path):
    errs = run_pack(tmp_path, concepts={"concepts": [{"id": "Service", "subclass_of": "Application"}]})
    assert any("redefines a core concept" in e for e in errs)


def test_pack_with_unknown_parent_fails(tmp_path):
    errs = run_pack(tmp_path, concepts={"concepts": [{"id": "Squad", "subclass_of": "Nothing"}]})
    assert any("must extend a known concept" in e for e in errs)


def test_pack_with_remove_key_fails(tmp_path):
    errs = run_pack(tmp_path, vocabularies={"extends": {"change_state": {"remove": ["rejected"]}}})
    assert any("never delete or redefine" in e for e in errs)


def test_pack_policy_that_allows_fails(tmp_path):
    errs = run_pack(tmp_path, policies={"policies": [{"id": "org.open", "effect": "allow"}]})
    assert any("could loosen access" in e for e in errs)


def test_pack_policy_reusing_core_id_fails(tmp_path):
    errs = run_pack(tmp_path, policies={"policies": [{"id": "core.deny_by_default", "effect": "deny"}]})
    assert any("core policy id" in e or "reserved core." in e for e in errs)


def test_pack_wrong_level_in_manifest_fails(tmp_path):
    errs = run_pack(tmp_path, manifest={"level": "project"})
    assert any("does not match folder" in e for e in errs)


def test_pack_not_additive_fails(tmp_path):
    errs = run_pack(tmp_path, manifest={"additive_only": False})
    assert any("additive_only" in e for e in errs)


def test_signed_pack_without_signature_fails(tmp_path):
    errs = run_pack(tmp_path, manifest={"signed": True})
    assert any("signature_ref" in e for e in errs)


def test_two_packs_defining_same_term_at_one_level_fail(tmp_path):
    seen = {}
    content = {"concepts": [{"id": "Squad", "subclass_of": "Team"}]}
    first = run_pack(tmp_path, seen=seen, concepts=content)
    (tmp_path / "p").rename(tmp_path / "p1")
    second = run_pack(tmp_path, seen=seen, concepts=content)
    assert first == [] and any("same level" in e for e in second)


def test_workflow_to_unknown_state_fails(tmp_path):
    errs = run_pack(tmp_path, level="project", workflow={"issue_workflow": [{"source_state": "X", "change_state": "flying"}]})
    assert any("unknown change_state" in e for e in errs)


def test_mapping_to_unknown_entity_fails(tmp_path):
    d = write_pack(tmp_path, level="app")
    (d / "mappings").mkdir()
    (d / "mappings" / "git.yml").write_text(yaml.safe_dump({"mappings": [{"source_object": "x", "entity": "Spaceship"}]}), encoding="utf-8")
    rep = co.Report()
    co.check_pack(rep, "app", d, co.check_core(co.Report()), {})
    assert any("unknown entity" in e for e in rep.errors)


# ---- templates ----
def template_errors(tmp_path, mutate):
    src = yaml.safe_load((ROOT / "templates" / "impact_of_change.yml").read_text(encoding="utf-8"))
    tpl = copy.deepcopy(src)
    mutate(tpl)
    d = tmp_path / "templates"
    d.mkdir()
    (d / "impact_of_change.yml").write_text(yaml.safe_dump(tpl), encoding="utf-8")
    old = co.ROOT
    co.ROOT = tmp_path
    try:
        rep = co.Report()
        co.check_templates(rep, {"concept_ids": co.CORE_CONCEPTS, "rel_ids": co.CORE_RELATIONSHIPS})
        return rep.errors
    finally:
        co.ROOT = old


def test_template_unchanged_passes(tmp_path):
    assert template_errors(tmp_path, lambda t: None) == []


def test_template_depth_above_three_fails(tmp_path):
    def m(t):
        t["limits"]["max_depth"] = 5
    assert any("max_depth" in e for e in template_errors(tmp_path, m))


def test_template_path_deeper_than_three_fails(tmp_path):
    def m(t):
        t["steps"][0]["cypher"] = t["steps"][0]["cypher"].replace("*1..3", "*1..6")
    assert any("deeper than" in e for e in template_errors(tmp_path, m))


def test_template_without_access_predicate_fails(tmp_path):
    def m(t):
        t["steps"][1]["cypher"] = t["steps"][1]["cypher"].replace("{{access_predicate}}", "true")
    assert any("access predicate" in e for e in template_errors(tmp_path, m))


def test_template_without_tenant_filter_fails(tmp_path):
    def m(t):
        t["steps"][1]["cypher"] = t["steps"][1]["cypher"].replace("$tenant_id", "'x'")
    assert any("tenant_id" in e for e in template_errors(tmp_path, m))


def test_template_without_limit_fails(tmp_path):
    def m(t):
        t["steps"][1]["cypher"] = t["steps"][1]["cypher"].replace("LIMIT $fanout_cap", "")
    assert any("no LIMIT" in e for e in template_errors(tmp_path, m))


def test_template_unknown_relationship_fails(tmp_path):
    def m(t):
        t["steps"][1]["cypher"] = t["steps"][1]["cypher"].replace(":owns", ":befriends")
    assert any("unknown relationship type" in e for e in template_errors(tmp_path, m))


def test_template_unknown_label_fails(tmp_path):
    def m(t):
        t["steps"][1]["cypher"] = t["steps"][1]["cypher"].replace("(t:Team", "(t:Spaceship")
    assert any("unknown node label" in e for e in template_errors(tmp_path, m))
