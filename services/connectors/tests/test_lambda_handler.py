from __future__ import annotations

import json

import pytest

import lambda_handler as lh
from common.source_document import SourceType
from config import Settings
from tests.conftest import FakeConnector, make_source_document
from tests.fake_s3 import FakeS3


class FakeClient:
    closed = False

    async def aclose(self):
        self.closed = True


def settings(**kw):
    return Settings(tenant_id=kw.pop("tenant_id", "t1"), s3={"bucket": kw.pop("bucket", "b")}, **kw)


def factory(connector, client=None):
    c = client or FakeClient()
    return lambda source, s: (c, connector)


def test_run_writes_snapshot_event_and_cursor_then_closes_client():
    s3, client = FakeS3(), FakeClient()
    conn = FakeConnector(SourceType.JIRA, [make_source_document()])
    out = lh.handler({"source": "jira"}, _s3=s3, _settings=settings(), _connector_factory=factory(conn, client))
    doc_version = "2026-01-01T00:00:00.000Z"
    assert out == {"source": "jira", "status": "success", "documents": 1, "object_errors": 0,
                   "cursors": {"default": doc_version}}
    assert [k for k in s3.objects if k.startswith("raw/jira/ABC-1/")]
    (evk,) = [k for k in s3.objects if k.startswith("bus/raw.jira/")]
    ev = json.loads(s3.objects[evk])
    assert ev["tenant_id"] == "t1" and ev["payload"]["snapshot_ref"].startswith("s3://b/raw/jira/ABC-1/")
    assert json.loads(s3.objects["state/connectors/jira%3Adefault.json"]) == {"cursor": doc_version}
    assert client.closed


def test_failure_raises_and_leaves_cursor():
    s3 = FakeS3()
    conn = FakeConnector(SourceType.JIRA, [], raises=True)
    with pytest.raises(lh.SyncFailed):
        lh.handler({"source": "jira"}, _s3=s3, _settings=settings(), _connector_factory=factory(conn))
    assert not [k for k in s3.objects if k.startswith("state/connectors/")]


def test_event_publish_failure_is_partial_not_raised_and_cursor_stays_on_the_failed_object():
    s3 = FakeS3()
    s3.fail_put_prefix = "bus/"
    conn = FakeConnector(SourceType.JIRA, [make_source_document()])
    out = lh.handler({"source": "jira"}, _s3=s3, _settings=settings(), _connector_factory=factory(conn))
    assert out["status"] == "partial" and out["object_errors"] == 1 and out["documents"] == 0
    # pinned to the failed object's version, so the next invocation fetches it again
    assert json.loads(s3.objects["state/connectors/jira%3Adefault.json"]) == {"cursor": "2026-01-01T00:00:00.000Z"}


def test_requires_source_bucket_and_tenant():
    with pytest.raises(ValueError, match="source"):
        lh.handler({}, _s3=FakeS3(), _settings=settings())
    with pytest.raises(ValueError, match="BUCKET"):
        lh.handler({"source": "jira"}, _s3=FakeS3(), _settings=settings(bucket=""))


def test_build_connector_builds_only_the_requested_source():
    client, conn = lh.build_connector("jira", Settings())
    assert conn.source == SourceType.JIRA
    with pytest.raises(ValueError):
        lh.build_connector("nope", Settings())


def test_secrets_manager_values_do_not_override_env(monkeypatch):
    class SM:
        def get_secret_value(self, SecretId):
            return {"SecretString": json.dumps({"USEP_INGESTION_JIRA_API_TOKEN": "from-sm", "OTHER": "x"})}
    monkeypatch.setenv("USEP_INGESTION_SECRETS_ARN", "arn:x")
    monkeypatch.delenv("USEP_INGESTION_JIRA_API_TOKEN", raising=False)
    lh._load_secrets(SM())
    import os
    assert os.environ["USEP_INGESTION_JIRA_API_TOKEN"] == "from-sm" and "OTHER" not in os.environ
    monkeypatch.delenv("USEP_INGESTION_JIRA_API_TOKEN")


@pytest.mark.parametrize("source", ["github", "servicenow", "ado"])
def test_build_connector_new_sources(source):
    client, conn = lh.build_connector(source, Settings())
    assert conn.source.value == source and source in lh.SOURCES
