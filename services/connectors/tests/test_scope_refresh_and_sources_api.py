from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import api_router
from common.connector_base import ScopeCheck, ScopeFetch, SourceCheck
from common.source_document import SourceType
from config import SchedulerSettings
from scheduler import IngestionScheduler, job_id
from sync_service import SyncService
from tests.conftest import FakeConnector


class Finding(FakeConnector):
    """A connector that finds its scopes by itself, like GitLab with all member repositories."""

    def __init__(self, found: list[list[str]]) -> None:
        super().__init__(SourceType.GITLAB, [])
        self._scopes = []  # nothing is known until the first refresh (FakeConnector would default to one scope)
        self._rounds = iter(found)
        self.broken = False

    async def refresh_scopes(self) -> None:
        if self.broken:
            raise ConnectionError("gitlab is down")
        self._scopes = next(self._rounds)

    async def check(self) -> SourceCheck:
        return SourceCheck(ok=True, scopes=[ScopeCheck(scope=s, ok=True) for s in self._scopes])


def _service(connectors, cursor_manager, raw_payload_writer, audit_writer) -> SyncService:
    return SyncService(
        connectors=connectors, cursor_manager=cursor_manager, writer_factory=lambda _r, _a: raw_payload_writer,
        audit_writer_factory=lambda _r: audit_writer,
    )


async def test_scopes_are_refreshed_and_a_failed_refresh_keeps_the_last_ones(cursor_manager, raw_payload_writer, audit_writer) -> None:
    connector = Finding([["1", "2"], ["1", "2", "3"]])
    service = _service({"gitlab": connector, "jira": FakeConnector(SourceType.JIRA, [])}, cursor_manager, raw_payload_writer, audit_writer)

    assert service.has_dynamic_scopes and service.scopes("gitlab") == []
    await service.refresh_scopes()
    assert service.scopes("gitlab") == ["1", "2"]

    connector.broken = True
    await service.refresh_scopes()  # must not raise
    assert service.scopes("gitlab") == ["1", "2"]


async def test_scheduler_adds_jobs_for_new_repositories_and_drops_the_ones_that_are_gone(cursor_manager, raw_payload_writer, audit_writer) -> None:
    connector = Finding([["1", "2"], ["2", "3"]])
    service = _service({"gitlab": connector}, cursor_manager, raw_payload_writer, audit_writer)
    scheduler = IngestionScheduler(service, SchedulerSettings(jitter_seconds=0))

    await service.refresh_scopes()
    scheduler._register_jobs()
    assert {j.id for j in scheduler._scheduler.get_jobs()} == {job_id("gitlab", "1"), job_id("gitlab", "2")}

    await scheduler._refresh()
    assert {j.id for j in scheduler._scheduler.get_jobs()} == {job_id("gitlab", "2"), job_id("gitlab", "3")}


async def test_a_source_that_is_not_selected_has_no_jobs_and_no_endpoint(cursor_manager, raw_payload_writer, audit_writer) -> None:
    service = _service({}, cursor_manager, raw_payload_writer, audit_writer)
    scheduler = IngestionScheduler(service, SchedulerSettings())

    scheduler._register_jobs()

    assert scheduler._scheduler.get_jobs() == [] and service.available_sources == [] and not service.has_dynamic_scopes


def _client(service, overview) -> TestClient:
    app = FastAPI()
    app.state.auth_disabled = True
    app.state.sync_service = service
    app.state.source_overview = overview
    app.include_router(api_router)
    return TestClient(app)


async def test_sources_api_lists_every_source_and_checks_only_selected_ones(cursor_manager, raw_payload_writer, audit_writer) -> None:
    connector = Finding([["g/a"]])
    await connector.refresh_scopes()
    service = _service({"gitlab": connector}, cursor_manager, raw_payload_writer, audit_writer)
    rows = [
        {"source": "jira", "enabled": False, "running": False, "scopes": [], "blocked_reason": None},
        {"source": "gitlab", "enabled": True, "running": True, "scopes": ["g/a"], "blocked_reason": None},
    ]
    client = _client(service, lambda: rows)

    listed = client.get("/sources")
    assert listed.status_code == 200 and listed.json() == rows

    checked = client.post("/sources/gitlab/check")
    assert checked.status_code == 200 and checked.json()["scopes"] == [{"scope": "g/a", "ok": True, "detail": ""}]
    assert client.post("/sources/jira/check").status_code == 404  # not selected: nothing to check


async def test_sources_endpoints_need_the_token(cursor_manager, raw_payload_writer, audit_writer) -> None:
    app = FastAPI()
    app.state.api_token = "s3cret"
    app.state.source_overview = lambda: []
    app.include_router(api_router)

    assert TestClient(app).get("/sources").status_code == 401
