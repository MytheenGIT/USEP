"""The pipeline Lambda takes its tenant's pins and signed releases from the registry, and follows a new release event,
including a version that was never in its own package (the old limit)."""
from pathlib import Path

import pytest
import yaml

from tests.fake_s3 import FakeS3
from tests.pipeline.helpers import BUCKET, TENANT, jira, raw_event
from tests.registry.test_registry import PINS, publish_all, trust_for
from usep.adapters.aws_lambda import pipeline_handler as ph
from usep.adapters.s3.event_bus import S3EventBus
from usep.core.errors import PipelineError
from usep.ontology.events import publish_release, register_schemas
from usep.pipeline.topics import register_schemas as register_topics
from usep.ports.event_bus import SchemaRegistry
from usep.registry import Ed25519Signer, Registry
from usep.registry.store import S3RegistryStore


@pytest.fixture()
def world(tmp_path, monkeypatch):
    s3, signer = FakeS3(), Ed25519Signer.generate("k1")
    reg = Registry(S3RegistryStore(s3, BUCKET), trust_for(signer), tmp_path / "rc")
    publish_all(reg, signer)
    trust = tmp_path / "trust.yaml"
    trust.write_text(yaml.safe_dump({"keys": [{"key_id": "k1", "alg": signer.alg, "public_key_pem": signer.public_pem()}]}), encoding="utf-8")
    sr = SchemaRegistry()
    register_schemas(sr)
    register_topics(sr, ("business", "architecture", "product", "security", "operations", "platform", "testing"))
    for k, v in {"USEP_BUS_BUCKET": BUCKET, "USEP_REGISTRY_BUCKET": BUCKET, "USEP_TENANT_ID": TENANT,
                 "USEP_TRUST_STORE": str(trust), "USEP_ONTOLOGY_ALLOW_REFERENCE": "true",
                 "USEP_ONTOLOGY_CACHE_DIR": str(tmp_path / "pc"), "USEP_ONTOLOGY_REFRESH_SECONDS": "0"}.items():
        monkeypatch.setenv(k, v)
    ph._state.clear(); ph._injected.clear()
    yield s3, reg, S3EventBus(s3, BUCKET, sr)
    ph._state.clear(); ph._injected.clear()


def test_pipeline_processes_a_record_under_the_registry_ontology(world):
    s3, reg, bus = world
    reg.set_pins(TENANT, PINS, "ops", allow_reference_only=True)
    s3.put_object(Bucket=BUCKET, Key="x", Body=b"")
    ev = raw_event(s3, "jira", "ABC-1", jira("ABC-1", "Task", "In Review"))
    bus.publish("raw.jira", ev.key, ev.type, TENANT, ev.payload)
    out = ph.handler({"poll": True}, _s3=s3)
    assert out["handled"] == 1 and out["entities"] == 1 and out["ontology_error"] is None
    assert out["ontology_digest"] == reg.current_pins(TENANT)["ontology_digest"]


def test_a_new_release_event_switches_the_running_pipeline_to_the_new_signed_pins(world):
    s3, reg, bus = world
    first = reg.set_pins(TENANT, PINS, "ops", allow_reference_only=True)
    assert ph.handler({}, _s3=s3)["ontology_digest"] == first["ontology_digest"]
    second = reg.set_pins(TENANT, PINS[:2], "ops", allow_reference_only=True,
                          on_release=lambda b, t: publish_release(bus, b, t))
    out = ph.handler({}, _s3=s3, _now=1e12)
    assert out["ontology_digest"] == second["ontology_digest"] != first["ontology_digest"] and out["ontology_error"] is None


def test_a_tampered_release_is_refused_and_the_old_ontology_stays(world):
    s3, reg, bus = world
    first = reg.set_pins(TENANT, PINS, "ops", allow_reference_only=True)
    ph.handler({}, _s3=s3)
    reg.set_pins(TENANT, PINS[:2], "ops", allow_reference_only=True, on_release=lambda b, t: publish_release(bus, b, t))
    key = "registry/releases/pack/org.org-reference/0.1.0/bundle.zip"
    s3.objects[key] = s3.objects[key] + b"x"
    out = ph.handler({}, _s3=s3, _now=1e12)
    assert out["ontology_digest"] == first["ontology_digest"] and "refused" in out["ontology_error"]


def test_a_tenant_with_no_pins_does_not_start(world):
    s3, _, _ = world
    with pytest.raises(PipelineError, match="no pinned ontology"):
        ph.build(s3)
