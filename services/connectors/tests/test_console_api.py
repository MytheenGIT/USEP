from __future__ import annotations

import base64
import json
import os
import time
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from common.connector_base import ScopeFetch, SourceCheck
from common.source_document import SourceType
from console_api.processor import ConfigProcessor, _Plan
from gitlab.models import GitLabCommit, GitLabDocument
from jira.models import JiraDocument

TOKEN = "tok-SECRET-should-never-leak"
NOW = datetime.now(UTC)
JIRA = {"enabled": True, "base_url": "https://acme.atlassian.net", "email": "dev@acme.test", "api_token": TOKEN, "project_keys": ["pay"]}
CONFLUENCE = {"enabled": True, "base_url": "https://acme.atlassian.net", "email": "dev@acme.test", "api_token": TOKEN, "space_keys": ["PAY", "OPS"]}
GITLAB = {"enabled": True, "base_url": "https://gitlab.example.com", "api_token": TOKEN, "project_paths": ["acme/checkout", "acme/billing"]}
FIGMA = {"enabled": True, "api_token": TOKEN, "file_keys": ["AbCdEf1234567890"]}
GITHUB = {"enabled": True, "api_token": TOKEN, "repositories": ["acme/checkout", "git@github.com:acme/billing.git", "https://github.com/acme/web.git"]}
SERVICENOW = {"enabled": True, "base_url": "https://dev1.service-now.com", "email": "svc-ingest", "api_token": TOKEN, "tables": ["incident", "Change_Request"]}
SSH_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmU=SECRETKEYBODY\n-----END OPENSSH PRIVATE KEY-----"
KNOWN_HOSTS = "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA"
ALL = {"name": "Payments", "connectors": {"jira": JIRA, "confluence": CONFLUENCE, "gitlab": GITLAB, "figma": FIGMA}}


class _Client:
    async def aclose(self) -> None:
        return None


class _Fake:
    """A connector with fixed documents and scopes, standing in for a real source."""

    def __init__(self, source: SourceType, docs=(), scopes=("default",), raises=False, lookup_fails=False) -> None:
        self.source, self._docs, self._scopes, self._raises = source, list(docs), list(scopes), raises
        self.fetched: list[str] = []
        if lookup_fails:
            async def refresh_scopes() -> None:
                raise PermissionError("401 Unauthorized")

            self.refresh_scopes = refresh_scopes

    @property
    def scopes(self) -> list[str]:
        return list(self._scopes)

    async def fetch_scope(self, scope: str, cursor):
        if self._raises:
            raise RuntimeError("figma down")
        self.fetched.append(scope)
        return ScopeFetch(documents=self._docs)

    async def check(self) -> SourceCheck:
        return SourceCheck(ok=True)


def _jira_doc() -> JiraDocument:
    return JiraDocument(
        source=SourceType.JIRA, source_type="issue", source_object_id="PAY-12", source_url="https://acme.atlassian.net/browse/PAY-12",
        retrieved_at=NOW, raw_payload={"fields": {"issuetype": {"name": "Story"}}}, title="Retry payments",
        issue_key="PAY-12", summary="Retry payments", status="Done", source_version="2026-11-01T00:00:00.000Z",
    )


def _gitlab_doc() -> GitLabDocument:
    return GitLabDocument(
        source=SourceType.GITLAB, source_type="merge_request", source_object_id="acme/checkout!7", source_url="https://gitlab.example.com/mr/7",
        retrieved_at=NOW, raw_payload={"iid": 7}, title="PAY-12 add retry", project_id="acme/checkout", mr_iid="7", state="merged",
        commits=[GitLabCommit(sha="a", message="PAY-12 retry", url="u", raw={})], source_version="2026-11-02T00:00:00.000Z",
    )


BEHAVIOUR: dict[str, str] = {}
PLANNED: dict[str, _Fake] = {}


def _make_client(tmp_path, monkeypatch, **extra_env):
    env = {
        "USEP_INGESTION_ADMIN_USERNAME": "admin", "USEP_INGESTION_ADMIN_PASSWORD": "s3cret-test",
        "USEP_INGESTION_OUTPUT_DIR": str(tmp_path), "USEP_INGESTION_SCHEDULER_ENABLED": "false",
        "USEP_INGESTION_TENANT_ID": str(uuid.uuid4()), "USEP_INGESTION_API_TOKEN": "service-token",
        "USEP_INGESTION_DEV_KEK_B64": base64.b64encode(os.urandom(32)).decode(),
        "USEP_INGESTION_DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path}/ingest.db",
        "USEP_INGESTION_ALLOW_PRIVATE_SOURCE_HOSTS": "true",  # no DNS in tests; the guard has its own tests
        "USEP_INGESTION_FIGMA_DPIA_APPROVED": "true",
        **extra_env,
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    BEHAVIOUR.clear()
    PLANNED.clear()

    def fake_plan(self, config):
        plans = []
        for key, summary in config.connectors.items():
            if not summary.enabled:
                continue
            if BEHAVIOUR.get(key) == "skip":
                plans.append(_Plan(key, skip_reason=f"{key} credentials are not available"))
                continue
            scopes = summary.targets + summary.jql_queries or ["default"]
            docs = {"jira": [_jira_doc()], "gitlab": [_gitlab_doc()]}.get(key, [])
            if BEHAVIOUR.get(key) == "lookup_fails":
                scopes = []
            if BEHAVIOUR.get(key) == "no_scopes":
                scopes = []
            connector = _Fake(SourceType(key), docs, scopes, raises=BEHAVIOUR.get(key) == "fail", lookup_fails=BEHAVIOUR.get(key) == "lookup_fails")
            PLANNED[key] = connector
            plans.append(_Plan(key, connector, _Client()))
        return plans

    monkeypatch.setattr(ConfigProcessor, "_plan", fake_plan)
    import main

    return TestClient(main.create_app())


@pytest.fixture
def client(tmp_path, monkeypatch):
    with _make_client(tmp_path, monkeypatch) as c:
        yield c


def _login(client, password="s3cret-test"):
    return client.post("/api/auth/login", json={"username": "admin", "password": password})


def _auth(client) -> dict:
    return {"Authorization": f"Bearer {_login(client).json()['token']}"}


def _wait_done(client, headers, config_id):
    for _ in range(200):
        cfg = client.get(f"/api/configurations/{config_id}", headers=headers).json()
        if cfg["status"] in ("ready", "failed"):
            return cfg
        time.sleep(0.05)
    raise AssertionError("configuration never finished")


def _only(**sections):
    return {"name": "Payments", "connectors": sections}


def _with(section: str, **changes):
    body = json.loads(json.dumps(ALL))
    body["connectors"][section].update(changes)
    return body


def test_login_rejects_bad_password_and_is_typed(client) -> None:
    r = _login(client, "wrong")
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials" and r.json()["trace_id"]


def test_login_fails_closed_without_configured_admin(tmp_path, monkeypatch) -> None:
    with _make_client(tmp_path, monkeypatch, USEP_INGESTION_ADMIN_USERNAME="", USEP_INGESTION_ADMIN_PASSWORD="") as c:
        assert c.post("/api/auth/login", json={"username": "", "password": ""}).status_code == 401


def test_login_is_throttled_after_repeated_failures(client) -> None:
    assert [_login(client, "wrong").status_code for _ in range(6)][-1] == 429
    assert _login(client).status_code == 429


def test_endpoints_require_a_session(client) -> None:
    # the console's routes need an admin session; the service's own routes need the service token
    for method, path in [("get", "/api/configurations"), ("get", "/api/connector-defaults"), ("post", "/api/connectors/jira/test"),
                         ("get", "/results/jira"), ("post", "/sync/jira"), ("get", "/sources")]:
        assert getattr(client, method)(path).status_code == 401, path
    assert client.get("/sources", headers={"Authorization": "Bearer service-token"}).status_code == 200
    assert client.get("/health").status_code == 200


def test_logout_revokes_token(client) -> None:
    headers = _auth(client)
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/configurations", headers=headers).status_code == 401


def test_defaults_report_server_side_connections_without_secrets(tmp_path, monkeypatch) -> None:
    with _make_client(tmp_path, monkeypatch, USEP_INGESTION_JIRA_BASE_URL="https://acme.atlassian.net",
                      USEP_INGESTION_JIRA_EMAIL="svc@acme.test", USEP_INGESTION_JIRA_API_TOKEN=TOKEN) as c:
        r = c.get("/api/connector-defaults", headers=_auth(c))
        assert r.status_code == 200
        body = r.json()
        assert body["jira"] == {"base_url": "https://acme.atlassian.net", "credentials_configured": True, "blocked_reason": None, "ssh_available": False}
        assert body["gitlab"]["credentials_configured"] is False
        assert TOKEN not in r.text


# ----- no connector is mandatory ------------------------------------------------------------------------------


@pytest.mark.parametrize("only", ["jira", "confluence", "gitlab"])
def test_any_single_connector_is_enough(client, only) -> None:
    body = _only(**{only: ALL["connectors"][only]})
    r = client.post("/api/configurations", json=body, headers=_auth(client))
    assert r.status_code == 201
    shown = r.json()["connectors"]
    assert [k for k, v in shown.items() if v["enabled"]] == [only]
    assert all(shown[k] == {"enabled": False, "base_url": None, "email": None, "targets": [], "jql_queries": [], "all_member_projects": False, "auth_method": "token", "encoded_query": "", "credentials": "none"}
               for k in shown if k != only)


def test_nothing_selected_is_refused(client) -> None:
    for connectors in ({}, {"jira": {"enabled": False}}, {"jira": {"base_url": "https://x.atlassian.net"}}):
        r = client.post("/api/configurations", json={"name": "x", "connectors": connectors}, headers=_auth(client))
        assert r.status_code == 422 and r.json()["fields"] == {"connectors": "Select at least one connector"}, connectors


def test_a_selected_connector_must_be_complete_but_the_others_are_not_asked(client) -> None:
    body = _only(jira={"enabled": True}, gitlab={"enabled": False})
    fields = client.post("/api/configurations", json=body, headers=_auth(client)).json()["fields"]
    assert set(fields) == {"jira.base_url", "jira.email", "jira.api_token", "jira.project_keys"}


def test_switching_a_connector_off_ignores_what_was_typed_in_it(client) -> None:
    body = _with("figma", enabled=False, api_token="", file_keys=["not a key"])
    r = client.post("/api/configurations", json=body, headers=_auth(client))
    assert r.status_code == 201 and r.json()["connectors"]["figma"]["enabled"] is False


# ----- what each connector accepts -----------------------------------------------------------------------------


def test_jira_accepts_several_project_keys_and_or_jql(client) -> None:
    headers = _auth(client)
    several = client.post("/api/configurations", json=_only(jira={**JIRA, "project_keys": ["pay", "OPS", "pay"]}), headers=headers).json()
    assert several["connectors"]["jira"]["targets"] == ["PAY", "OPS"]

    jql_only = {**JIRA, "project_keys": [], "jql_queries": ["labels = release", "  labels = release  ", "assignee = currentUser()"]}
    only = client.post("/api/configurations", json=_only(jira=jql_only), headers=headers)
    assert only.status_code == 201
    assert only.json()["connectors"]["jira"]["jql_queries"] == ["labels = release", "assignee = currentUser()"]


def test_jira_needs_a_project_key_or_a_jql(client) -> None:
    r = client.post("/api/configurations", json=_only(jira={**JIRA, "project_keys": [], "jql_queries": []}), headers=_auth(client))
    assert r.status_code == 422 and r.json()["fields"] == {"jira.project_keys": "Add at least one project key or a JQL query"}


def test_errors_are_per_connector_field(client) -> None:
    body = _with("jira", api_token="", project_keys=["PAY OR 1=1"], base_url="http://acme.atlassian.net")
    body["name"] = ""
    fields = client.post("/api/configurations", json=body, headers=_auth(client)).json()["fields"]
    assert set(fields) == {"name", "jira.api_token", "jira.project_keys", "jira.base_url"}


def test_a_jql_query_cannot_hide_control_characters_or_be_huge(client) -> None:
    for bad in ("project = A\x00", "x" * 2001):
        r = client.post("/api/configurations", json=_only(jira={**JIRA, "jql_queries": [bad]}), headers=_auth(client))
        assert r.status_code == 422 and "jira.jql_queries" in r.json()["fields"]


def test_confluence_takes_many_space_keys_and_space_links(client) -> None:
    spaces = ["pay", "OPS", "https://acme.atlassian.net/wiki/spaces/ENG/overview", "OPS"]
    r = client.post("/api/configurations", json=_only(confluence={**CONFLUENCE, "space_keys": spaces}), headers=_auth(client))
    assert r.status_code == 201 and r.json()["connectors"]["confluence"]["targets"] == ["pay", "OPS", "ENG"]
    bad = client.post("/api/configurations", json=_only(confluence={**CONFLUENCE, "space_keys": ['ENG" OR space = "X']}), headers=_auth(client))
    assert bad.status_code == 422 and set(bad.json()["fields"]) == {"confluence.space_keys"}


def test_gitlab_takes_many_repositories_or_all_of_them(client) -> None:
    headers = _auth(client)
    many = client.post("/api/configurations", json=_only(gitlab=GITLAB), headers=headers).json()["connectors"]["gitlab"]
    assert many["targets"] == ["acme/checkout", "acme/billing"] and many["all_member_projects"] is False

    everything = {**GITLAB, "project_paths": [], "all_member_projects": True}
    r = client.post("/api/configurations", json=_only(gitlab=everything), headers=headers)
    assert r.status_code == 201 and r.json()["connectors"]["gitlab"]["all_member_projects"] is True

    nothing = client.post("/api/configurations", json=_only(gitlab={**GITLAB, "project_paths": []}), headers=headers)
    assert nothing.status_code == 422 and "all repositories" in nothing.json()["fields"]["gitlab.project_paths"]


def test_figma_waits_for_the_dpia(tmp_path, monkeypatch) -> None:
    with _make_client(tmp_path, monkeypatch, USEP_INGESTION_FIGMA_DPIA_APPROVED="false") as c:
        r = c.post("/api/configurations", json=_only(figma=FIGMA), headers=_auth(c))
        assert r.status_code == 422 and "DPIA" in r.json()["fields"]["figma.file_keys"]
        assert c.post("/api/configurations", json=_only(jira=JIRA), headers=_auth(c)).status_code == 201  # the others are unaffected


def test_email_is_required_for_atlassian_but_not_gitlab(client) -> None:
    f1 = client.post("/api/configurations", json=_with("jira", email=""), headers=_auth(client)).json()["fields"]
    assert set(f1) == {"jira.email"}
    body = json.loads(json.dumps(ALL))
    body["connectors"]["gitlab"].pop("email", None)
    assert client.post("/api/configurations", json=body, headers=_auth(client)).status_code == 201


def test_private_host_is_blocked_by_default(tmp_path, monkeypatch) -> None:
    with _make_client(tmp_path, monkeypatch, USEP_INGESTION_ALLOW_PRIVATE_SOURCE_HOSTS="false") as c:
        r = c.post("/api/configurations", json=_with("gitlab", base_url="https://169.254.169.254"), headers=_auth(c))
        assert r.status_code == 422 and "private or internal" in r.json()["fields"]["gitlab.base_url"]


def test_server_credentials_option_needs_server_credentials(client) -> None:
    body = _with("jira", use_server_credentials=True, api_token="", email="")
    r = client.post("/api/configurations", json=body, headers=_auth(client))
    assert r.status_code == 422 and "no Jira credentials" in r.json()["fields"]["jira.api_token"]


# ----- processing -----------------------------------------------------------------------------------------------


def test_a_single_selected_source_gives_a_ready_graph_without_the_others(client) -> None:
    headers = _auth(client)
    cfg = client.post("/api/configurations", json=_only(jira=JIRA), headers=headers).json()

    done = _wait_done(client, headers, cfg["id"])

    assert done["status"] == "ready" and done["status_detail"] is None
    assert [(s["source"], s["state"]) for s in done["sources"]] == [("jira", "success")]  # nothing about the others
    assert sorted(PLANNED) == ["jira"]
    graph = client.get(f"/api/configurations/{cfg['id']}/graph", headers=headers).json()
    assert {n["id"]: n["concept"] for n in graph["nodes"]} == {"jira:PAY-12": "Requirement"}


def test_every_selected_source_read_gives_the_full_graph_and_never_leaks_secrets(client, tmp_path) -> None:
    headers = _auth(client)
    created = client.post("/api/configurations", json=ALL, headers=headers)
    assert created.status_code == 201
    cfg = created.json()
    assert cfg["status"] == "submitted" and cfg["connectors"]["jira"] == {
        "enabled": True, "base_url": "https://acme.atlassian.net", "email": "dev@acme.test", "targets": ["PAY"],
        "jql_queries": [], "all_member_projects": False, "auth_method": "token", "encoded_query": "", "credentials": "provided",
    }

    done = _wait_done(client, headers, cfg["id"])
    assert done["status"] == "ready"
    assert {s["source"]: s["state"] for s in done["sources"]} == {"jira": "success", "confluence": "success", "gitlab": "success", "figma": "success"}
    assert PLANNED["confluence"].fetched == ["PAY", "OPS"] and PLANNED["gitlab"].fetched == ["acme/checkout", "acme/billing"]  # every entry read

    graph = client.get(f"/api/configurations/{cfg['id']}/graph", headers=headers).json()
    assert {n["id"]: n["concept"] for n in graph["nodes"]} == {"jira:PAY-12": "Requirement", "gitlab:acme/checkout!7": "Change"}
    assert [(e["relation"], e["source"], e["target"]) for e in graph["edges"]] == [("implements", "gitlab:acme/checkout!7", "jira:PAY-12")]

    everything = (created.text + json.dumps(done) + json.dumps(graph)).encode()
    for path in tmp_path.rglob("*"):  # every saved file, the raw objects and the database included
        if path.is_file():
            everything += path.read_bytes()
    assert TOKEN.encode() not in everything
    assert client.app.state.secrets.get(cfg["id"], "jira") is None


def test_a_console_run_lands_the_raw_objects_through_the_real_pipeline(client, tmp_path) -> None:
    headers = _auth(client)
    cfg = client.post("/api/configurations", json=_only(jira=JIRA, gitlab=GITLAB), headers=headers).json()
    _wait_done(client, headers, cfg["id"])

    objects = [p for p in (tmp_path / "raw").rglob("*.json")]
    assert len(objects) == 2  # one raw object per document, written by the foundation's writer
    assert all(b"Retry payments" not in p.read_bytes() for p in objects)  # encrypted on disk
    assert any("/jira/" in p.as_posix() for p in objects) and any("/gitlab/" in p.as_posix() for p in objects)


@pytest.mark.parametrize("behaviour", ["fail", "skip"])
def test_one_unreadable_selected_source_means_not_ready_and_no_graph(client, behaviour) -> None:
    headers = _auth(client)
    BEHAVIOUR["figma"] = behaviour
    cfg = client.post("/api/configurations", json=ALL, headers=headers).json()
    done = _wait_done(client, headers, cfg["id"])
    assert done["status"] == "failed"
    assert {s["source"]: s["state"] for s in done["sources"]}["figma"] == ("failed" if behaviour == "fail" else "skipped")
    assert "Figma" in done["status_detail"] and "Jira" not in done["status_detail"]
    assert client.get(f"/api/configurations/{cfg['id']}/graph", headers=headers).status_code == 409


def test_a_source_that_is_not_selected_never_makes_a_configuration_fail(client) -> None:
    headers = _auth(client)
    BEHAVIOUR["figma"] = "fail"  # would fail, but Figma is not selected
    cfg = client.post("/api/configurations", json=_only(jira=JIRA), headers=headers).json()
    assert _wait_done(client, headers, cfg["id"])["status"] == "ready"


def test_defaults_tell_the_form_that_figma_is_blocked_until_the_dpia(tmp_path, monkeypatch) -> None:
    with _make_client(tmp_path, monkeypatch, USEP_INGESTION_FIGMA_DPIA_APPROVED="false") as c:
        body = c.get("/api/connector-defaults", headers=_auth(c)).json()
        assert "DPIA" in body["figma"]["blocked_reason"] and body["jira"]["blocked_reason"] is None


@pytest.mark.parametrize(("behaviour", "expected"), [("lookup_fails", "Could not list what to read"), ("no_scopes", "no repositories were found")])
def test_a_failed_or_empty_repository_lookup_is_a_failure_not_an_empty_success(client, behaviour, expected) -> None:
    headers = _auth(client)
    BEHAVIOUR["gitlab"] = behaviour
    body = _only(gitlab={**GITLAB, "project_paths": [], "all_member_projects": True}, jira=JIRA)
    cfg = client.post("/api/configurations", json=body, headers=headers).json()

    done = _wait_done(client, headers, cfg["id"])

    assert done["status"] == "failed" and expected in done["status_detail"] and "Jira" not in done["status_detail"]
    states = {s["source"]: s["state"] for s in done["sources"]}
    assert states == {"jira": "success", "gitlab": "failed"}  # Jira was still read; only GitLab failed
    assert client.get(f"/api/configurations/{cfg['id']}/graph", headers=headers).status_code == 409


# ----- GitHub, ServiceNow, SSH keys, token naming ---------------------------------------------------------------


def test_github_takes_repositories_as_names_https_links_or_ssh_links(client) -> None:
    r = client.post("/api/configurations", json=_only(github=GITHUB), headers=_auth(client))
    assert r.status_code == 201
    assert r.json()["connectors"]["github"]["targets"] == ["acme/checkout", "acme/billing", "acme/web"]


def test_github_needs_a_repository_or_all_of_them(client) -> None:
    headers = _auth(client)
    none = client.post("/api/configurations", json=_only(github={**GITHUB, "repositories": []}), headers=headers)
    assert none.status_code == 422 and "all repositories" in none.json()["fields"]["github.repositories"]
    everything = client.post("/api/configurations", json=_only(github={**GITHUB, "repositories": [], "all_member_projects": True}), headers=headers)
    assert everything.status_code == 201 and everything.json()["connectors"]["github"]["all_member_projects"] is True
    bad = client.post("/api/configurations", json=_only(github={**GITHUB, "repositories": ["just-a-name"]}), headers=headers)
    assert bad.status_code == 422 and "owner/repo" in bad.json()["fields"]["github.repositories"]


def test_github_website_url_is_rejected_with_a_clear_message(client) -> None:
    for url in ("https://github.com", "https://github.com/", "https://www.github.com"):
        r = client.post("/api/configurations", json=_only(github={**GITHUB, "base_url": url}), headers=_auth(client))
        assert r.status_code == 422 and "api.github.com" in r.json()["fields"]["github.base_url"]


def test_servicenow_takes_a_username_a_password_and_tables(client) -> None:
    r = client.post("/api/configurations", json=_only(servicenow=SERVICENOW), headers=_auth(client))
    assert r.status_code == 201
    shown = r.json()["connectors"]["servicenow"]
    assert (shown["email"], shown["targets"], shown["credentials"]) == ("svc-ingest", ["incident", "change_request"], "provided")  # no @ needed in a username

    blank = client.post("/api/configurations", json=_only(servicenow={"enabled": True}), headers=_auth(client)).json()["fields"]
    assert blank == {
        "servicenow.base_url": "ServiceNow URL is required", "servicenow.email": "Username is required",
        "servicenow.api_token": "Password is required", "servicenow.tables": "Add at least one table, for example incident",
    }


def test_servicenow_tables_and_query_are_checked(client) -> None:
    headers = _auth(client)
    bad = client.post("/api/configurations", json=_only(servicenow={**SERVICENOW, "tables": ["incident/../sys_user"]}), headers=headers)
    assert bad.status_code == 422 and "servicenow.tables" in bad.json()["fields"]
    ok = client.post("/api/configurations", json=_only(servicenow={**SERVICENOW, "encoded_query": "active=true^priority<=2"}), headers=headers)
    assert ok.status_code == 201 and ok.json()["connectors"]["servicenow"]["encoded_query"] == "active=true^priority<=2"
    long = client.post("/api/configurations", json=_only(servicenow={**SERVICENOW, "encoded_query": "x" * 1001}), headers=headers)
    assert long.status_code == 422 and "servicenow.encoded_query" in long.json()["fields"]


def test_the_secret_is_called_token_everywhere_and_password_for_servicenow(client) -> None:
    for name, section in (("jira", JIRA), ("confluence", CONFLUENCE), ("gitlab", GITLAB), ("github", GITHUB), ("figma", FIGMA)):
        fields = client.post("/api/configurations", json=_only(**{name: {**section, "api_token": ""}}), headers=_auth(client)).json()["fields"]
        assert fields[f"{name}.api_token"] == "Token is required", name
    assert "API token" not in client.post("/api/configurations", json=_only(jira={**JIRA, "api_token": ""}), headers=_auth(client)).text


def test_an_ssh_key_can_replace_the_token_when_the_server_knows_the_hosts(tmp_path, monkeypatch) -> None:
    with _make_client(tmp_path, monkeypatch, USEP_INGESTION_SSH_KNOWN_HOSTS=KNOWN_HOSTS) as c:
        headers = _auth(c)
        assert c.get("/api/connector-defaults", headers=headers).json()["github"]["ssh_available"] is True
        assert c.get("/api/connector-defaults", headers=headers).json()["jira"]["ssh_available"] is False

        body = _only(github={"enabled": True, "auth_method": "ssh_key", "ssh_key": SSH_KEY, "repositories": ["git@github.com:acme/billing.git"]})
        created = c.post("/api/configurations", json=body, headers=headers)
        assert created.status_code == 201
        shown = created.json()["connectors"]["github"]
        assert (shown["auth_method"], shown["credentials"], shown["targets"]) == ("ssh_key", "provided", ["acme/billing"])

        done = _wait_done(c, headers, created.json()["id"])
        everything = (created.text + json.dumps(done)).encode()
        for path in tmp_path.rglob("*"):
            if path.is_file():
                everything += path.read_bytes()
        assert b"SECRETKEYBODY" not in everything  # the key is never stored, returned or logged
        assert c.app.state.secrets.get(created.json()["id"], "github") is None


def test_ssh_works_for_the_public_platforms_and_other_hosts_need_the_operator(client) -> None:
    headers = _auth(client)
    assert client.get("/api/connector-defaults", headers=headers).json()["github"]["ssh_available"] is True
    ssh = {"enabled": True, "auth_method": "ssh_key", "ssh_key": SSH_KEY, "repositories": ["acme/billing"]}
    assert client.post("/api/configurations", json=_only(github=ssh), headers=headers).status_code == 201
    own = {"enabled": True, "auth_method": "ssh_key", "ssh_key": SSH_KEY, "base_url": "https://gitlab.example.com", "project_paths": ["acme/billing"]}
    r = client.post("/api/configurations", json=_only(gitlab=own), headers=headers)
    assert r.status_code == 422 and "gitlab.example.com" in r.json()["fields"]["gitlab.ssh_key"]


def test_ssh_key_checks(tmp_path, monkeypatch) -> None:
    with _make_client(tmp_path, monkeypatch, USEP_INGESTION_SSH_KNOWN_HOSTS=KNOWN_HOSTS) as c:
        headers = _auth(c)
        base = {"enabled": True, "auth_method": "ssh_key", "ssh_key": SSH_KEY, "repositories": ["acme/billing"]}
        cases = [
            ({**base, "ssh_key": "ssh-ed25519 AAAA user@host"}, "github.ssh_key"),
            ({**base, "ssh_key": "-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\n\nabc\n-----END RSA PRIVATE KEY-----"}, "github.ssh_key"),
            ({**base, "all_member_projects": True}, "github.all_member_projects"),
            ({**base, "use_server_credentials": True}, "github.api_token"),
        ]
        for section, field in cases:
            r = c.post("/api/configurations", json=_only(github=section), headers=headers)
            assert r.status_code == 422 and field in r.json()["fields"], section
        # the other connectors do not offer SSH: a stray auth_method is ignored, and the token is still required
        r = c.post("/api/configurations", json=_only(jira={**JIRA, "api_token": "", "auth_method": "ssh_key", "ssh_key": SSH_KEY}), headers=headers)
        assert r.status_code == 422 and r.json()["fields"] == {"jira.api_token": "Token is required"}


def test_repositories_can_be_listed_for_choosing(client, monkeypatch) -> None:
    from console_api.models import RepositoryChoice, RepositoryList
    from console_api import routes

    seen = {}

    async def fake(spec, parsed, settings, runtime_for):
        seen.update(source=spec.key, token=parsed.credentials.secret, base=parsed.base_url)
        return RepositoryList(repositories=[RepositoryChoice(path="acme/checkout", name="checkout", visibility="private")], truncated=False)

    monkeypatch.setattr(routes, "list_repositories", fake)
    headers = _auth(client)
    r = client.post("/api/connectors/github/repositories", json={"enabled": True, "api_token": TOKEN}, headers=headers)
    assert r.status_code == 200 and r.json()["repositories"][0]["path"] == "acme/checkout"
    assert seen == {"source": "github", "token": TOKEN, "base": "https://api.github.com"}  # the server's default address
    assert client.post("/api/connectors/jira/repositories", json=JIRA, headers=headers).status_code == 404
    assert client.post("/api/connectors/github/repositories", json={"enabled": True}, headers=headers).status_code == 422  # no token typed yet
    assert client.post("/api/connectors/github/repositories", json={"enabled": True, "api_token": TOKEN}).status_code == 401


# ----- adding a connector to a configuration that is already ready --------------------------------------------------


def _ready(client, headers, body) -> dict:
    cfg = client.post("/api/configurations", json=body, headers=headers).json()
    done = _wait_done(client, headers, cfg["id"])
    assert done["status"] == "ready"
    return done


def _add(client, headers, config_id, **sections):
    return client.post(f"/api/configurations/{config_id}/connectors", json={"connectors": sections}, headers=headers)


def test_another_connector_can_be_added_and_the_graph_keeps_what_was_read_before(client, tmp_path) -> None:
    headers = _auth(client)
    cfg = _ready(client, headers, _only(jira=JIRA, gitlab=GITLAB))
    PLANNED.clear()

    r = _add(client, headers, cfg["id"], confluence=CONFLUENCE)

    assert r.status_code == 200 and r.json()["status"] == "processing"
    assert [k for k, v in r.json()["connectors"].items() if v["enabled"]] == ["jira", "confluence", "gitlab"]
    done = _wait_done(client, headers, cfg["id"])
    assert done["status"] == "ready" and done["status_detail"] is None
    assert {s["source"]: s["state"] for s in done["sources"]} == {"jira": "success", "gitlab": "success", "confluence": "success"}
    assert PLANNED["confluence"].fetched and not PLANNED["jira"].fetched and not PLANNED["gitlab"].fetched  # only the new one was read
    graph = client.get(f"/api/configurations/{cfg['id']}/graph", headers=headers).json()
    assert {n["id"] for n in graph["nodes"]} == {"jira:PAY-12", "gitlab:acme/checkout!7"}  # rebuilt from the saved results
    assert [e["relation"] for e in graph["edges"]] == ["implements"]
    assert (tmp_path / "configurations" / cfg["id"] / "sources" / "jira.json").is_file()


def test_the_token_of_the_new_connector_is_not_kept_or_shown(client, tmp_path) -> None:
    headers = _auth(client)
    cfg = _ready(client, headers, _only(jira=JIRA))
    added = _add(client, headers, cfg["id"], confluence=CONFLUENCE)
    done = _wait_done(client, headers, cfg["id"])

    everything = (added.text + json.dumps(done)).encode()
    for path in tmp_path.rglob("*"):
        if path.is_file():
            everything += path.read_bytes()
    assert TOKEN.encode() not in everything
    assert client.app.state.secrets.get(cfg["id"], "confluence") is None


def test_a_connector_that_cannot_be_read_is_taken_out_again_and_the_graph_stays(client) -> None:
    headers = _auth(client)
    cfg = _ready(client, headers, _only(jira=JIRA))
    before = client.get(f"/api/configurations/{cfg['id']}/graph", headers=headers).json()
    BEHAVIOUR["confluence"] = "fail"

    _add(client, headers, cfg["id"], confluence=CONFLUENCE)
    done = _wait_done(client, headers, cfg["id"])

    assert done["status"] == "ready" and "Could not add Confluence" in done["status_detail"]
    assert done["connectors"]["confluence"]["enabled"] is False and [s["source"] for s in done["sources"]] == ["jira"]
    assert client.get(f"/api/configurations/{cfg['id']}/graph", headers=headers).json()["nodes"] == before["nodes"]


def test_one_new_connector_can_succeed_while_another_fails(client) -> None:
    headers = _auth(client)
    cfg = _ready(client, headers, _only(jira=JIRA))
    BEHAVIOUR["gitlab"] = "fail"

    _add(client, headers, cfg["id"], gitlab=GITLAB, confluence=CONFLUENCE)
    done = _wait_done(client, headers, cfg["id"])

    assert done["status"] == "ready" and "Could not add GitLab" in done["status_detail"] and "Confluence" not in done["status_detail"]
    assert [k for k, v in done["connectors"].items() if v["enabled"]] == ["jira", "confluence"]
    assert {s["source"] for s in done["sources"]} == {"jira", "confluence"}


def test_adding_is_refused_when_it_would_leave_the_graph_incomplete(client, tmp_path) -> None:
    headers = _auth(client)
    cfg = _ready(client, headers, _only(jira=JIRA))
    (tmp_path / "configurations" / cfg["id"] / "sources" / "jira.json").unlink()  # a configuration made before results were saved
    PLANNED.clear()

    _add(client, headers, cfg["id"], confluence=CONFLUENCE)
    done = _wait_done(client, headers, cfg["id"])

    assert done["status"] == "ready" and "saved results for Jira are missing" in done["status_detail"]
    assert done["connectors"]["confluence"]["enabled"] is False and PLANNED == {}  # the new token was never used


def test_what_can_and_cannot_be_added(client) -> None:
    headers = _auth(client)
    cfg = _ready(client, headers, _only(jira=JIRA))
    assert _add(client, headers, cfg["id"], jira=JIRA).json()["fields"] == {"connectors": "Jira is already in this configuration"}
    assert _add(client, headers, cfg["id"]).json()["fields"] == {"connectors": "Select at least one connector to add"}
    assert _add(client, headers, cfg["id"], confluence={"enabled": True}).status_code == 422  # a new one must be complete
    assert _add(client, headers, "01a21b20-a20e-75be-8f9b-80bc8d845006", confluence=CONFLUENCE).status_code == 404
    assert client.post(f"/api/configurations/{cfg['id']}/connectors", json={"connectors": {"confluence": CONFLUENCE}}).status_code == 401
    # nothing above changed the configuration
    assert [k for k, v in client.get(f"/api/configurations/{cfg['id']}", headers=headers).json()["connectors"].items() if v["enabled"]] == ["jira"]


def test_a_configuration_that_is_not_ready_cannot_take_another_connector(client) -> None:
    headers = _auth(client)
    BEHAVIOUR["jira"] = "fail"
    cfg = client.post("/api/configurations", json=_only(jira=JIRA), headers=headers).json()
    assert _wait_done(client, headers, cfg["id"])["status"] == "failed"
    r = _add(client, headers, cfg["id"], confluence=CONFLUENCE)
    assert r.status_code == 409 and r.json()["code"] == "not_ready"
