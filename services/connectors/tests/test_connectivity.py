from __future__ import annotations

import pytest

from common.connector_base import ScopeCheck, SourceCheck
from config import Settings
from console_api import connectivity
from console_api.models import ConnectorSummary
from console_api.secrets_store import Credentials
from console_api.validation import SPECS, ParsedConnector

SECRET = "tok-SECRET-should-never-leak"


class FakeClient:
    closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeConnector:
    def __init__(self, result: SourceCheck | Exception) -> None:
        self._result = result

    async def check(self) -> SourceCheck:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _parsed(targets: list[str], **summary) -> ParsedConnector:
    return ParsedConnector(
        summary=ConnectorSummary(enabled=True, base_url="https://acme.atlassian.net", targets=targets, credentials="provided", **summary),
        base_url="https://acme.atlassian.net", credentials=Credentials("dev@acme.test", SECRET),
    )


@pytest.fixture
def use_connector(monkeypatch):
    seen: dict = {}

    def install(result: SourceCheck | Exception) -> FakeClient:
        client = FakeClient()

        def build(key, **kwargs):
            seen.update(key=key, **kwargs)
            return FakeConnector(result), client

        monkeypatch.setattr(connectivity, "build_connector", build)
        return client

    install.seen = seen  # type: ignore[attr-defined]
    return install


def _ok(*scopes: str, detail: str = "signed in") -> SourceCheck:
    return SourceCheck(ok=True, detail=detail, scopes=[ScopeCheck(scope=s, ok=True) for s in scopes])


async def test_success_counts_what_was_reachable(use_connector) -> None:
    client = use_connector(_ok("PAY", "OPS"))
    result = await connectivity.check_connection(SPECS["jira"], _parsed(["PAY", "OPS"]), Settings())
    assert result.ok and result.message == "Connected. 2 project keys reachable"
    assert client.closed


async def test_the_connector_is_built_from_exactly_what_was_entered(use_connector) -> None:
    use_connector(_ok())
    await connectivity.check_connection(
        SPECS["jira"], _parsed(["PAY"], jql_queries=["labels = release"]), Settings()
    )
    seen = use_connector.seen
    assert (seen["key"], seen["targets"], seen["jql_queries"], seen["base_url"]) == ("jira", ["PAY"], ["labels = release"], "https://acme.atlassian.net")
    assert seen["creds"].secret == SECRET


async def test_a_bad_scope_is_named_with_the_sources_reason_and_a_good_one_is_not(use_connector) -> None:
    use_connector(SourceCheck(ok=False, scopes=[ScopeCheck(scope="PAY", ok=True), ScopeCheck(scope="NOPE", ok=False, detail="HTTP 404")]))
    result = await connectivity.check_connection(SPECS["confluence"], _parsed(["PAY", "NOPE"]), Settings())
    assert not result.ok and "'NOPE': HTTP 404" in result.message and "'PAY'" not in result.message
    assert SECRET not in result.message


async def test_a_refused_token_is_reported_without_leaking_it(use_connector) -> None:
    use_connector(SourceCheck(ok=False, detail="cannot sign in: HTTP 401"))
    result = await connectivity.check_connection(SPECS["jira"], _parsed(["PAY"]), Settings())
    assert not result.ok and result.message == "Jira: cannot sign in: HTTP 401" and SECRET not in result.message


async def test_a_failing_call_is_a_message_not_an_exception(use_connector) -> None:
    client = use_connector(RuntimeError(f"boom {SECRET}"))
    result = await connectivity.check_connection(SPECS["jira"], _parsed(["PAY"]), Settings())
    assert not result.ok and result.message == "Jira: the request failed" and SECRET not in result.message
    assert client.closed


async def test_long_scopes_and_many_failures_stay_readable(use_connector) -> None:
    bad = [ScopeCheck(scope="project = " + "X" * 200, ok=False, detail="HTTP 400") for _ in range(6)]
    use_connector(SourceCheck(ok=False, scopes=bad))
    message = (await connectivity.check_connection(SPECS["jira"], _parsed([]), Settings())).message
    assert "..." in message and "(and 2 more)" in message and len(message) < 400


async def test_gitlab_says_how_many_more_repositories_membership_found(use_connector) -> None:
    use_connector(_ok("group/a", detail="12 more found from membership"))
    result = await connectivity.check_connection(SPECS["gitlab"], _parsed(["group/a"], all_member_projects=True), Settings())
    assert result.ok and result.message == "Connected. 1 projects reachable. 12 more found from membership"


async def test_figma_cannot_be_tested_without_a_file(use_connector) -> None:
    use_connector(SourceCheck(ok=False, detail="add a file to test the token with"))
    result = await connectivity.check_connection(SPECS["figma"], _parsed([]), Settings())
    assert not result.ok and "add a file" in result.message


async def test_no_credentials_at_all(use_connector) -> None:
    use_connector(_ok())
    parsed = _parsed([])
    parsed.credentials = None
    result = await connectivity.check_connection(SPECS["jira"], parsed, Settings())
    assert not result.ok and "No Jira credentials" in result.message
