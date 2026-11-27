"""Worker idempotency, schema drift and the Lambda entry point."""
import json

from tests.fake_s3 import FakeS3
from tests.pipeline.helpers import BUCKET, ONT, TENANT, jira, published, raw_event
from usep.adapters.aws_lambda import pipeline_handler as ph
from usep.adapters.s3.event_bus import S3EventBus
from usep.core.ids import uuid7
from usep.ontology import load_ontology
from usep.pipeline.topics import register_schemas
from usep.ports.event_bus import SchemaRegistry




def test_schema_drift_in_snapshot_is_quarantined(env):
    s3, _, w = env
    out = w.handle(raw_event(s3, "jira", "ABC-11", {"unexpected": True}))
    assert out.reasons == ["Q-PARSE"]


def test_entity_event_is_idempotent_key_stable_across_replays(env):
    s3, _, w = env
    ev = raw_event(s3, "jira", "ABC-12", jira("ABC-12", "Task", "Done"))
    w.handle(ev)
    w.handle(ev)
    keys = [e["headers"]["idempotency_key"] for e in published(s3, "entity.product")]
    assert len(keys) == 2 and keys[0] == keys[1]
    assert len([k for k in s3.objects if k.startswith("evidence/")]) == 1          # written once


def test_lambda_handles_s3_notification_and_poll(bundle, monkeypatch):
    s3 = FakeS3()
    monkeypatch.setenv("USEP_BUS_BUCKET", BUCKET)
    monkeypatch.setenv("USEP_BUS_PARTITIONS", "4")
    ph._state.clear()
    # a connector-style raw event on the bus
    reg = SchemaRegistry()
    register_schemas(reg, bundle.domains)
    bus = S3EventBus(s3, BUCKET, reg, partitions=4)
    ev = raw_event(s3, "jira", "ABC-13", jira("ABC-13", "Task", "Done"))
    key = f"bus/raw.jira/p000/{ev.event_id}.json"
    s3.objects[key] = json.dumps(ev.__dict__).encode()
    loader = lambda pins: bundle
    notif = {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": key}}},
                         {"s3": {"bucket": {"name": BUCKET}, "object": {"key": "bus/_offsets/raw.jira/g/p000.json"}}}]}
    r = ph.handler(notif, _s3=s3, _loader=loader)
    assert r["handled"] == 1 and r["entities"] == 1
    r = ph.handler({"poll": True}, _s3=s3, _loader=loader)
    assert r["handled"] == 1                      # poll drains from offsets, independent of notifications
    assert ph.handler({"poll": True}, _s3=s3, _loader=loader)["handled"] == 0



# ---------------------------------------------------------------- ontology release refresh
def _release_setup(monkeypatch, tenant=TENANT):
    from usep.ontology.events import publish_release, register_schemas as reg_onto
    monkeypatch.setenv("USEP_BUS_BUCKET", BUCKET)
    monkeypatch.setenv("USEP_BUS_PARTITIONS", "4")
    monkeypatch.setenv("USEP_TENANT_ID", tenant)
    monkeypatch.setenv("USEP_ONTOLOGY_PINS", "app.app-reference@0.1.0,project.project-reference@0.1.0")
    ph._state.clear()
    ph._injected.clear()
    old = load_ontology(ONT, ["app.app-reference@0.1.0", "project.project-reference@0.1.0"], allow_reference_only=True)
    new = load_ontology(ONT, ["app.app-reference@0.1.0", "project.project-reference@0.1.0", "org.org-reference@0.1.0"],
                        allow_reference_only=True)
    reg = SchemaRegistry()
    register_schemas(reg, old.domains)
    reg_onto(reg)
    s3 = FakeS3()
    bus = S3EventBus(s3, BUCKET, reg, partitions=4)
    loader = lambda pins: load_ontology(ONT, pins, allow_reference_only=True)
    return s3, bus, old, new, loader, publish_release


def test_new_release_is_picked_up_and_reported(monkeypatch):
    s3, bus, old, new, loader, publish = _release_setup(monkeypatch)
    r = ph.handler({"Records": []}, _s3=s3, _loader=loader, _now=1000.0)
    assert r["ontology_digest"] == old.release.digest and r["ontology_error"] is None
    publish(bus, new, TENANT)
    r = ph.handler({"Records": []}, _s3=s3, _loader=loader, _now=2000.0)
    assert r["ontology_digest"] == new.release.digest and r["ontology_error"] is None


def test_refresh_is_throttled(monkeypatch):
    s3, bus, old, new, loader, publish = _release_setup(monkeypatch)
    monkeypatch.setenv("USEP_ONTOLOGY_REFRESH_SECONDS", "60")
    ph.handler({"Records": []}, _s3=s3, _loader=loader, _now=1000.0)
    publish(bus, new, TENANT)
    assert ph.handler({"Records": []}, _s3=s3, _loader=loader, _now=1030.0)["ontology_digest"] == old.release.digest
    assert ph.handler({"Records": []}, _s3=s3, _loader=loader, _now=1061.0)["ontology_digest"] == new.release.digest


def test_release_naming_a_pack_not_in_the_package_is_refused(monkeypatch):
    s3, bus, old, new, loader, publish = _release_setup(monkeypatch)
    ph.handler({"Records": []}, _s3=s3, _loader=loader, _now=1000.0)
    bundle_with_ghost = new.release.as_dict()
    bundle_with_ghost["packs"].append({"id": "app.not-shipped", "level": "application", "version": "9.9.9"})
    bus.publish("ontology.release", TENANT, "ontology.released", TENANT, bundle_with_ghost)
    r = ph.handler({"Records": []}, _s3=s3, _loader=loader, _now=2000.0)
    assert r["ontology_digest"] == old.release.digest and "refused" in r["ontology_error"]   # fail closed, says why


def test_other_tenants_release_is_ignored(monkeypatch):
    s3, bus, old, new, loader, publish = _release_setup(monkeypatch)
    ph.handler({"Records": []}, _s3=s3, _loader=loader, _now=1000.0)
    publish(bus, new, str(uuid7()))
    assert ph.handler({"Records": []}, _s3=s3, _loader=loader, _now=2000.0)["ontology_digest"] == old.release.digest


def test_without_tenant_id_refresh_is_off_and_ontology_fixed(monkeypatch):
    s3, bus, old, new, loader, publish = _release_setup(monkeypatch)
    monkeypatch.delenv("USEP_TENANT_ID")
    r = ph.handler({"Records": []}, _s3=s3, _loader=loader, _now=1000.0)
    assert r["ontology_digest"] == old.release.digest and r["ontology_error"] is None


# ---------------------------------------------------------------- SQS delivery (S3 -> SQS -> Lambda)
def _sqs(message_id, keys, bucket=BUCKET):
    import json as _j
    body = {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": k}}} for k in keys]}
    return {"eventSource": "aws:sqs", "messageId": message_id, "body": _j.dumps(body)}


def _put_raw_event(s3, ref, raw):
    ev = raw_event(s3, "jira", ref, raw)
    key = f"bus/raw.jira/p000/{ev.event_id}.json"
    s3.objects[key] = json.dumps(ev.__dict__).encode()
    return key


def test_sqs_batch_reports_only_the_failed_message(bundle, monkeypatch):
    monkeypatch.setenv("USEP_BUS_BUCKET", BUCKET)
    monkeypatch.setenv("USEP_BUS_PARTITIONS", "4")
    ph._state.clear()
    ph._injected.clear()
    s3 = FakeS3()
    good = _put_raw_event(s3, "ABC-40", jira("ABC-40", "Task", "Done"))
    event = {"Records": [_sqs("m-ok", [good]), _sqs("m-missing", ["bus/raw.jira/p000/does-not-exist.json"]),
                         {"eventSource": "aws:sqs", "messageId": "m-test", "body": json.dumps({"Event": "s3:TestEvent"})}]}
    r = ph.handler(event, _s3=s3, _loader=lambda pins: bundle)
    assert r["batchItemFailures"] == [{"itemIdentifier": "m-missing"}]       # only that message is retried
    assert r["handled"] == 1 and r["entities"] == 1                          # test event ignored, good one processed


def test_sqs_success_returns_no_failures(bundle, monkeypatch):
    monkeypatch.setenv("USEP_BUS_BUCKET", BUCKET)
    monkeypatch.setenv("USEP_BUS_PARTITIONS", "4")
    ph._state.clear()
    ph._injected.clear()
    s3 = FakeS3()
    key = _put_raw_event(s3, "ABC-41", jira("ABC-41", "Task", "Done"))
    r = ph.handler({"Records": [_sqs("m1", [key, "bus/_offsets/raw.jira/g/p000.json"])]}, _s3=s3, _loader=lambda pins: bundle)
    assert r["batchItemFailures"] == [] and r["handled"] == 1
