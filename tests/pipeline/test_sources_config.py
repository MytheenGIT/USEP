from pathlib import Path

import pytest

from tests.pipeline.helpers import BUCKET, jira, published, raw_event
from usep.adapters.s3.snapshot_store import S3SnapshotStore
from usep.pipeline.normalize.record import Acl
from usep.pipeline.sources_config import SourcesConfigError, apply_mappings, load_acl_mappings
from usep.pipeline.worker import AcquisitionWorker

SHIPPED = Path(__file__).resolve().parents[2] / "config" / "sources.yaml"


def test_shipped_file_has_no_mappings_and_is_valid():
    assert load_acl_mappings(SHIPPED) == {}


def test_mapping_only_restricts_and_adds_principals():
    base = Acl(False, "", (), False, ("project:ABC",))
    out = apply_mappings("jira", base, {"jira:project:ABC": ("group:abc-team",)})
    assert out.known and out.restricted and out.principals == ("group:abc-team",) and out.scopes == base.scopes
    assert apply_mappings("jira", base, {"jira:project:XYZ": ("group:x",)}) is base          # no match: unchanged
    assert apply_mappings("gitlab", base, {"jira:project:ABC": ("group:abc-team",)}) is base   # source is part of the key


def test_bad_mapping_is_rejected(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("sources:\n  jira:\n    acl_mappings:\n      'project:ABC': [nogroup]\n", encoding="utf-8")
    with pytest.raises(SourcesConfigError):
        load_acl_mappings(f)


def test_worker_applies_a_mapping_and_the_record_stays_owners_only(env, bundle):
    s3, bus, _ = env
    w = AcquisitionWorker(bus, S3SnapshotStore(s3, BUCKET), lambda: bundle,
                          acl_mappings={"jira:project:ABC": ("group:abc-team",)})
    ev = raw_event(s3, "jira", "ABC-1", jira("ABC-1", "Task", "In Review"))
    ev.payload["acl"] = {"project_key": "ABC"}
    w.handle(ev)
    p = published(s3, "entity.product")[0]["payload"]
    assert p["labels"]["acl_state"] == "known" and p["labels"]["owners_only"] is True
    assert "group:abc-team" in p["labels"]["acl"]["principals"]
