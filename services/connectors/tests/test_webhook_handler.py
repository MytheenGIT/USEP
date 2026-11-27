import base64
import hashlib
import hmac
import json

import pytest

import webhook_handler as wh


class FakeLambda:
    def __init__(self):
        self.calls = []

    def invoke(self, **kw):
        self.calls.append(kw)


def sig(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("USEP_CONNECTOR_FUNCTION", "usep-dev-connectors")
    monkeypatch.setenv("USEP_SOURCES_FILE", "/nonexistent.yaml")        # no file: every source enabled
    for s in ("GITHUB", "GITLAB", "JIRA", "ADO"):
        monkeypatch.setenv(f"USEP_INGESTION_WEBHOOK_SECRET_{s}", f"s3cret-{s.lower()}")


def call(source, headers, body=b"{}", **extra):
    fl = FakeLambda()
    ev = {"rawPath": f"/webhook/{source}", "headers": headers, "body": body.decode(), **extra}
    return wh.handler(ev, _lambda=fl), fl


def test_github_hmac_accepted_and_triggers_one_incremental_sync():
    body = b'{"zen":"x"}'
    r, fl = call("github", {"X-Hub-Signature-256": sig("s3cret-github", body)}, body)
    assert r["statusCode"] == 202 and len(fl.calls) == 1
    c = fl.calls[0]
    assert c["FunctionName"] == "usep-dev-connectors" and c["InvocationType"] == "Event"
    assert json.loads(c["Payload"]) == {"source": "github", "mode": "sync", "trigger": "webhook"}


def test_payload_content_never_reaches_the_sync_request():
    body = b'{"scope":"; DROP TABLE","source":"jira"}'
    r, fl = call("jira", {"x-hub-signature": sig("s3cret-jira", body)}, body)
    assert json.loads(fl.calls[0]["Payload"])["source"] == "jira" and b"DROP" not in fl.calls[0]["Payload"]


def test_gitlab_and_ado_token_headers():
    assert call("gitlab", {"X-Gitlab-Token": "s3cret-gitlab"})[0]["statusCode"] == 202
    assert call("ado", {"x-usep-webhook-token": "s3cret-ado"})[0]["statusCode"] == 202


@pytest.mark.parametrize("source,headers", [
    ("github", {"X-Hub-Signature-256": "sha256=00"}), ("github", {}), ("gitlab", {"X-Gitlab-Token": "wrong"}),
    ("confluence", {"X-Hub-Signature-256": "sha256=00"}),          # no secret configured: refused, same answer
    ("servicenow", {"x-usep-webhook-token": ""}),
])
def test_bad_or_unconfigured_calls_are_refused_and_start_nothing(source, headers):
    r, fl = call(source, headers)
    assert r["statusCode"] == 401 and fl.calls == []


def test_unknown_source_oversize_and_base64():
    assert call("nosuch", {})[0]["statusCode"] == 404
    assert call("github", {}, b"x" * (wh.MAX_BODY + 1))[0]["statusCode"] == 413
    body = b'{"a":1}'
    r, fl = call("github", {"X-Hub-Signature-256": sig("s3cret-github", body)}, base64.b64encode(body), isBase64Encoded=True)
    assert r["statusCode"] == 202 and len(fl.calls) == 1


def test_disabled_source_is_ignored(tmp_path, monkeypatch):
    f = tmp_path / "s.yaml"
    f.write_text("sources:\n  gitlab: {enabled: false}\n", encoding="utf-8")
    monkeypatch.setenv("USEP_SOURCES_FILE", str(f))
    r, fl = call("gitlab", {"X-Gitlab-Token": "s3cret-gitlab"})
    assert r["statusCode"] == 202 and fl.calls == []
