"""Scenarios A-G, I, J from the labelling brief, plus resolver and claim rules."""
import pytest

from usep.graph import GraphNode, KnowledgeGraph
from usep.graph.adapters.graphify import to_graphify
from usep.graph.projection import GraphProjectionService, RelationshipClaim
from usep.labelling import Labeller, LabelDefinition, PropertyDef, effective_properties, validate_definition
from usep.labelling.claims import Claim, resolve_claims

from conftest import T1, T2

GIT_REPO = {"name": "checkout-service", "repository": "acme/checkout", "source_id": "acme/checkout",
            "source_version": "7", "acl_state": "known", "sensitivity": 1}


def lab(view, defs=(), tenant=T1, system="git", obj="repository", payload=GIT_REPO):
    return Labeller(view, defs).label(tenant, system, obj, payload)


def defn(**kw):
    base = dict(id="squad", tenant_id=T1, level="organization", parent_concept="Team", display_name="Squad", status="active")
    return LabelDefinition(**{**base, **kw})


# ---- A core ------------------------------------------------------------------------------------
def test_a_git_repository_becomes_service(view):
    r = lab(view)
    assert (r.processing_status, r.concept, r.domain, r.confidence) == ("labelled", "Service", "architecture", 1.0)
    assert r.properties["repository_ref"] == "acme/checkout" and r.entity_id and r.valid_from
    assert r.mapping_rule_id and "deterministic" in r.explanation[0]
    assert r.field_provenance["concept"].layer == "application"
    assert r.ontology_version == view.bundle.pins.core_version


def test_missing_required_and_bad_vocab_are_quarantined_with_reason(view):
    r = lab(view, payload={**GIT_REPO, "name": ""})
    assert (r.processing_status, r.reason_code) == ("quarantined", "Q-SCHEMA")
    assert any(v.code == "required_missing" and v.field == "name" for v in r.validation_results)
    r = lab(view, obj="adr", payload={"title": "Use X", "status": "maybe", "source_id": "adr-1"})
    assert r.reason_code == "Q-SCHEMA" and any(v.code == "vocab_value" for v in r.validation_results)


def test_vocabulary_is_normalised(view):
    r = lab(view, obj="adr", payload={"title": "Use X", "status": " Accepted ", "source_id": "adr-1"})
    assert r.ok and r.properties["status"] == "accepted"


def test_temporal_and_sensitivity_checks(view):
    r = lab(view, payload={**GIT_REPO, "valid_from": "2026-02-01T00:00:00Z", "valid_to": "2026-01-01T00:00:00Z", "sensitivity": 9})
    codes = {v.code for v in r.validation_results}
    assert r.reason_code == "Q-SCHEMA" and {"temporal", "vocab_value"} <= codes


def test_missing_tenant_is_quarantined(view):
    assert lab(view, tenant="").reason_code == "Q-TENANT"


# ---- B domain ----------------------------------------------------------------------------------
def test_b_domain_label_resolves_to_core_parent(view):
    r = lab(view, system="grc", obj="control", payload={"title": "Req 3", "framework": "pci_dss", "id": "c-3", "acl_state": "known"})
    assert r.ok and r.concept == "ComplianceControl" and r.ontology_level == "industry"
    values = {l.value: l for l in r.custom_labels}
    assert values["Control"].level == "core" and "subclass of Control" in values["Control"].reason
    assert r.domain == "security"          # inherited from the parent, not redefined


# ---- C organisation ----------------------------------------------------------------------------
def test_c_org_alias_keeps_team_canonical(view):
    r = lab(view, obj="team", payload={"name": "payments", "source_id": "payments", "source_term": "Squad", "acl_state": "known"})
    assert r.concept == "Team"
    assert any(l.value == "Squad" and l.level == "organization" and l.kind == "alias" for l in r.custom_labels)


# ---- D application -----------------------------------------------------------------------------
def test_d_jira_mapping_and_unknown_type_quarantined(view):
    ok = lab(view, system="jira", obj="issue", payload={"issue_type": "bug", "issue": {"summary": "S", "key": "A-1", "status": "To Do"}})
    assert ok.ok and ok.concept == "Change" and ok.source_id == "A-1"
    bad = lab(view, system="jira", obj="issue", payload={"issue_type": "spike", "issue": {"summary": "S", "key": "A-2"}})
    assert (bad.processing_status, bad.reason_code, bad.concept) == ("quarantined", "Q-UNMAPPED-TYPE", None)
    assert lab(view, system="nope", obj="x", payload={}).reason_code == "Q-UNMAPPED-TYPE"


def test_unlisted_git_object_is_evidence_not_dropped_or_guessed(view):
    r = lab(view, obj="readme", payload={})
    assert r.processing_status == "evidence" and r.concept is None


# ---- E/F custom metadata, defaults ---------------------------------------------------------------
def test_e_custom_label_validate_preview_and_effective(view):
    d = defn(id="tiered_team", display_name="Tiered Team", level="application", source_systems=("git",), source_types=("team",),
             properties=(PropertyDef("cost_centre", "string", True, "CC-000", pattern=r"CC-\d{3}"),))
    assert validate_definition(d, view) == []
    r = lab(view, [d], obj="team", payload={"name": "p", "source_id": "p", "acl_state": "known"})
    assert r.ok and r.properties["cost_centre"] == "CC-000"
    assert any(l.source == "tiered_team" for l in r.custom_labels)
    assert effective_properties(view, "Team", [d])["cost_centre"].origin == "custom"
    r = lab(view, [d.with_status("draft")], obj="team", payload={"name": "p", "source_id": "p"})
    assert "cost_centre" not in r.properties          # drafts and disabled definitions have no effect


def test_f_default_override_shows_inherited_and_effective_and_resets(view):
    d = defn(id="svc_default", level="application", parent_concept="Service", display_name="Svc",
             properties=(PropertyDef("criticality", "enum", default="tier_2"),))
    assert validate_definition(d, view) == []
    eff = effective_properties(view, "Service", [d])["criticality"]
    assert (eff.origin, eff.default, eff.value_layer) == ("overridden", "tier_2", "application")
    assert [c["layer"] for c in eff.contributions] == ["core", "application"]
    assert lab(view, [d]).properties["criticality"] == "tier_2"
    assert effective_properties(view, "Service", [d.with_status("disabled")])["criticality"].origin == "inherited"   # reset


def test_most_specific_level_wins(view):
    org = defn(id="o", parent_concept="Service", properties=(PropertyDef("criticality", "enum", default="tier_3"),))
    app = defn(id="a", level="application", parent_concept="Service", display_name="A", properties=(PropertyDef("criticality", "enum", default="tier_1"),))
    assert effective_properties(view, "Service", [app, org])["criticality"].default == "tier_1"


@pytest.mark.parametrize("kw,fragment", [
    (dict(level="core"), "immutable"),
    (dict(parent_concept="Widget"), "not in the active ontology"),
    (dict(id="Bad Id"), "lower_snake_case"),
    (dict(properties=(PropertyDef("name", "string", required=False),)), "required property optional"),
    (dict(properties=(PropertyDef("criticality", "enum", allowed_values=("tier_1", "tier_9")),)), "only narrow"),
    (dict(properties=(PropertyDef("criticality", "enum", default="tier_9"),)), "not an allowed value"),
    (dict(properties=(PropertyDef("repository_ref", "integer"),)), "inherited type"),
    (dict(properties=(PropertyDef("tenant_id", "string"),)), "reserved"),
    (dict(properties=(PropertyDef("x", "string", pattern="(["),)), "invalid pattern"),
    (dict(properties=(PropertyDef("x", "weird"),)), "unknown type"),
    (dict(relationship_rules=("befriends",)), "not in the active ontology"),
])
def test_invalid_definitions_rejected_server_side(view, kw, fragment):
    base = dict(parent_concept="Service") if "parent_concept" not in kw else {}
    errs = validate_definition(defn(**{**base, **kw}), view)
    assert any(fragment in e for e in errs), errs


def test_duplicate_term_same_level_fails_and_other_tenant_is_invisible(view):
    a = defn()
    assert any("CC-16" in e for e in validate_definition(defn(id="squad2"), view, [a]))
    assert validate_definition(defn(id="squad2", tenant_id=T2), view, [a]) == []        # other tenant's term is not our conflict
    assert "id belongs to another tenant" in validate_definition(defn(tenant_id=T2), view, [a])


def test_weakening_property_is_ignored_when_resolving(view):
    bad = defn(id="bad", parent_concept="Service", properties=(PropertyDef("name", "string", required=False),))
    assert effective_properties(view, "Service", [bad])["name"].required is True


def test_definitions_of_another_tenant_never_apply(view):
    r = lab(view, [defn(tenant_id=T2)], obj="team", payload={"name": "p", "source_id": "p", "acl_state": "known"})
    assert not any(l.source == "squad" for l in r.custom_labels)


# ---- G graph -------------------------------------------------------------------------------------
def nodes(view):
    def mk(system, obj, payload):
        r = lab(view, system=system, obj=obj, payload={**payload, "acl_state": "known"})
        assert r.ok, r.explanation
        return r
    return {
        "team": mk("git", "team", {"name": "payments", "source_id": "payments", "source_term": "Squad"}),
        "svc": mk("git", "repository", {"name": "checkout", "repository": "acme/checkout", "source_id": "acme/checkout"}),
        "chg": mk("jira", "issue", {"issue_type": "bug", "issue": {"summary": "fix", "key": "A-1", "status": "Done"}}),
        "req": mk("jira", "issue", {"issue_type": "story", "issue": {"summary": "need", "key": "A-2", "status": "Open"}}),
    }


def test_g_projection_is_deterministic_idempotent_and_carries_provenance(view):
    n = nodes(view)
    svc = GraphProjectionService(view)
    claims = [RelationshipClaim(T1, n["team"].entity_id, n["svc"].entity_id, "owns", "CODEOWNERS", "git"),
              RelationshipClaim(T1, n["chg"].entity_id, n["req"].entity_id, "implements", "jira:link", "jira")]
    first = svc.project(T1, n.values(), claims)
    assert first.ok and (first.nodes_added, first.edges_added) == (4, 2)
    again = svc.project(T1, n.values(), claims, existing=first.graph)
    assert again.ok and (again.nodes_added, again.edges_added, again.edges_skipped_duplicate) == (0, 0, 2)
    assert to_graphify(first.graph) == to_graphify(again.graph) == to_graphify(svc.project(T1, reversed(list(n.values())), claims).graph)
    node = next(x for x in to_graphify(first.graph)["nodes"] if x["type"] == "Team")
    assert node["metadata"]["tenant_id"] == T1 and "Squad" in node["metadata"]["labels"]
    assert node["metadata"]["versions"]["ontology_version"] == view.bundle.pins.core_version
    assert node["metadata"]["provenance"]["mapping_rule_id"]
    edge = to_graphify(first.graph)["links"][0]
    assert edge["metadata"]["tenant_id"] == T1 and edge["metadata"]["edge_id"] and edge["source_location"]


def test_i_invalid_relationship_rejected_and_not_projected(view):
    n = nodes(view)
    test = lab(view, system="git", obj="team", payload={"name": "x", "source_id": "x"})   # stand-in node, retyped below
    res = GraphProjectionService(view).project(T1, [n["team"], n["svc"]], [
        RelationshipClaim(T1, n["svc"].entity_id, n["team"].entity_id, "owns"),            # Service owns Team: invalid
        RelationshipClaim(T1, n["team"].entity_id, n["svc"].entity_id, "befriends")])      # not in ontology
    assert {e.code for e in res.errors} == {"endpoint_type", "unknown_relationship"}
    assert res.graph.edges == [] and "cannot start at Service" in res.errors[0].message + res.errors[1].message


def test_test_owns_team_rejected(view):
    assert "cannot start at Test" in view.endpoint_ok("owns", "Test", "Team")
    assert view.endpoint_ok("owns", "ComplianceControl", "Team") is not None
    assert view.endpoint_ok("governed_by", "Service", "ComplianceControl") is None      # subclass of Control is allowed


def test_j_tenant_isolation_in_projection(view):
    n = nodes(view)
    other = lab(view, tenant=T2, obj="team", payload={"name": "z", "source_id": "z", "acl_state": "known"})
    svc = GraphProjectionService(view)
    res = svc.project(T1, [n["team"], other], [RelationshipClaim(T2, n["team"].entity_id, n["svc"].entity_id, "owns")])
    assert [e.code for e in res.errors].count("cross_tenant") == 2 and len(res.graph.nodes) == 1
    foreign = KnowledgeGraph([GraphNode("x", "Team", "t", tenant_id=T2)])
    assert svc.project(T1, [], [], existing=foreign).errors[0].code == "cross_tenant"
    mixed = KnowledgeGraph([GraphNode("a", "Team", "t", tenant_id=T1), GraphNode("b", "Team", "t", tenant_id=T2)])
    assert any("mixes tenants" in p for p in mixed.problems({"Team"}, set()))


def test_quarantined_records_never_become_nodes(view):
    bad = lab(view, system="jira", obj="issue", payload={"issue_type": "spike"})
    res = GraphProjectionService(view).project(T1, [bad])
    assert res.errors[0].code == "not_labelled" and res.graph.nodes == []


def test_missing_endpoint_node_is_reported(view):
    n = nodes(view)
    res = GraphProjectionService(view).project(T1, [n["team"]], [RelationshipClaim(T1, n["team"].entity_id, "ghost", "owns")])
    assert res.errors[0].code == "missing_node"


# ---- claims ----------------------------------------------------------------------------------------
PREC = {"owner_ref": ["cmdb", "git", "confluence"]}


def test_claims_precedence_conflict_is_recorded_and_all_claims_kept(view):
    cs = [Claim("owner_ref", "team-a", "confluence", "p1", "9"), Claim("owner_ref", "team-b", "git", "r1", "1")]
    r = resolve_claims("owner_ref", cs, view.precedence)
    assert r.conflict and r.winner.value == "team-b" and len(r.claims) == 2 and "precedence" in r.reason


def test_claims_without_rule_have_no_winner_even_if_newer():
    r = resolve_claims("summary", [Claim("summary", "a", "git", "1", "1"), Claim("summary", "b", "jira", "2", "99")], PREC)
    assert r.winner is None and r.conflict and "stays open" in r.reason


def test_claims_agreement_and_tiebreaks():
    assert not resolve_claims("owner_ref", [Claim("owner_ref", "a", "git"), Claim("owner_ref", "a", "confluence")], PREC).conflict
    r = resolve_claims("owner_ref", [Claim("owner_ref", "a", "git", "1", "1"), Claim("owner_ref", "b", "git", "2", "2")], PREC)
    assert r.winner.value == "b" and "source_version" in r.reason
    r = resolve_claims("owner_ref", [Claim("owner_ref", "a", "git", "2", "1"), Claim("owner_ref", "b", "git", "1", "1")], PREC, ["git"])
    assert r.winner.value == "b" and "tie-break" in r.reason
