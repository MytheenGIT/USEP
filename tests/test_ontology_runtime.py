import shutil
from pathlib import Path

import pytest
import yaml

from tests.fake_s3 import FakeS3
from usep.core.errors import OntologyLoadError, SchemaViolation
from usep.core.ids import uuid7
from usep.adapters.s3.event_bus import S3EventBus
from usep.ontology import load_ontology, map_record, validate
from usep.ontology.events import OntologyConfigCache, publish_release, register_schemas
from usep.ports.event_bus import SchemaRegistry, consume

ONT = Path(__file__).resolve().parents[1] / "ontology"
PINS = ["app.app-reference@0.1.0", "org.org-reference@0.1.0", "industry.banking-reference@0.1.0"]
TENANT = str(uuid7())


def load(root=ONT, pins=PINS, **kw):
    return load_ontology(root, pins, allow_reference_only=True, **kw)


def test_loads_core_and_pins_and_digest_is_stable():
    a, b = load(), load()
    assert (len(a.concepts), len(a.relationships), len(a.templates)) == (18, 14, 8)
    assert a.release.digest == b.release.digest
    assert [p.id for p in a.release.packs][0] == "core"
    assert a.concepts["ComplianceControl"].parent == "Control"


def test_reference_pack_refused_by_default():
    with pytest.raises(OntologyLoadError, match="reference-only"):
        load_ontology(ONT, PINS[:1])


def test_missing_and_wrong_version_pin_fail_closed():
    with pytest.raises(OntologyLoadError) as e:
        load(pins=["app.nope@0.1.0", "org.org-reference@9.9.9"])
    assert len(e.value.problems) == 2


def test_pack_redefining_core_concept_or_loosening_policy_rejected(tmp_path):
    root = tmp_path / "ontology"
    shutil.copytree(ONT, root)
    bank = root / "packs/industry/banking-reference"
    (bank / "concepts.yml").write_text(yaml.safe_dump({"concepts": [{"id": "Service", "domain": "x"}]}))
    (bank / "policies.yml").write_text(yaml.safe_dump({"policies": [{"id": "p", "effect": "allow"}]}))
    with pytest.raises(OntologyLoadError) as e:
        load(root, ["industry.banking-reference@0.1.0"])
    text = " ".join(e.value.problems)
    assert "already defined" in text and "only tighten" in text


def test_pack_requires_other_core_version(tmp_path):
    root = tmp_path / "ontology"
    shutil.copytree(ONT, root)
    mf = root / "packs/app/app-reference/pack.yml"
    mf.write_text(mf.read_text().replace(">=0.1.0 <1.0.0", ">=2.0.0"))
    with pytest.raises(OntologyLoadError, match="requires core"):
        load(root, ["app.app-reference@0.1.0"])


def node(**over):
    a = {"tenant_id": TENANT, "entity_id": str(uuid7()), "domain": "product", "sensitivity": 1,
         "source_system": "jira", "source_id": "ABC-1", "source_version": "1", "name": "x",
         "valid_from": "2026-01-01T00:00:00.000Z", "recorded_at": "2026-01-02T00:00:00.000Z"}
    a.update(over)
    return a


def test_gate_maps_jira_issue_and_validates():
    b = load()
    m = map_record(b, "jira", "issue", {"issue": {"issue_type": "bug", "summary": "s", "key": "ABC-1"}})
    assert m.ok and m.candidate.type == "Change"
    assert validate(b, type(m.candidate)("node", "Change", node())).ok


def test_gate_quarantines_unmapped_type_without_content():
    r = map_record(load(), "jira", "issue", {"issue": {"issue_type": "spike", "summary": "secret text"}})
    assert not r.ok and r.quarantine.reason_code == "Q-UNMAPPED"
    assert "secret" not in r.quarantine.reason


@pytest.mark.parametrize("over,field", [
    ({"tenant_id": None}, "tenant_id"), ({"sensitivity": 7}, "sensitivity"), ({"domain": "nope"}, "domain"),
    ({"valid_to": "2025-01-01T00:00:00Z"}, "valid_to"), ({"entity_id": "not-a-uuid"}, "entity_id")])
def test_gate_rejects_bad_nodes(over, field):
    from usep.ontology import Candidate
    r = validate(load(), Candidate("node", "Change", node(**over)))
    assert not r.ok and r.quarantine.reason_code == "Q-SCHEMA" and field in r.quarantine.location


def test_gate_edge_endpoints():
    from usep.ontology import Candidate
    b = load()
    assert validate(b, Candidate("edge", "implements", {}, "Change", "Requirement")).ok
    assert not validate(b, Candidate("edge", "owns", {}, "Test", "Team")).ok


def make_bus():
    reg = SchemaRegistry()
    register_schemas(reg)
    return S3EventBus(FakeS3(), "b", reg, partitions=4)


def test_bus_orders_per_key_and_commits():
    bus = make_bus()
    for i in range(5):
        bus.publish("ontology.release", "k", "t", TENANT, {"core_version": "0", "packs": [], "digest": str(i)})
    got = []
    consume(bus, "ontology.release", "g", lambda e: got.append(e.payload["digest"]))
    assert got == list("01234")
    assert bus.poll("ontology.release", "g") == []
    bus.reset("ontology.release", "g")
    assert len(bus.poll("ontology.release", "g")) == 5            # replay


def test_bus_rejects_invalid_payload_and_missing_tenant():
    bus = make_bus()
    with pytest.raises(SchemaViolation):
        bus.publish("ontology.release", "k", "t", TENANT, {"digest": "x"})


def test_config_cache_follows_release_and_fails_closed():
    bus, loaded = make_bus(), load()
    cache = OntologyConfigCache(TENANT, "g", lambda pins: load(pins=pins))
    publish_release(bus, loaded, TENANT)
    assert cache.refresh(bus) and cache.current.release.digest == loaded.release.digest
    bus.publish("ontology.release", TENANT, "ontology.released", TENANT,
                {"core_version": "0.1.0", "packs": [{"id": "app.gone", "level": "application", "version": "1.0.0"}],
                 "digest": "f" * 64})
    assert not cache.refresh(bus) and "refused" in cache.last_error
    assert cache.current.release.digest == loaded.release.digest   # kept the previous ontology
