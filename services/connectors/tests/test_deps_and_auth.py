from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import api_router
from common.interfaces.audit_writer import AuditEvent, StructlogAuditWriter


def _app(tmp_path, **state) -> TestClient:
    app = FastAPI()
    app.state.output_dir = str(tmp_path)
    for name, value in state.items():
        setattr(app.state, name, value)
    app.include_router(api_router)
    return TestClient(app)


def test_health_is_open_without_a_token(tmp_path) -> None:
    assert _app(tmp_path, api_token="s3cret").get("/health").status_code == 200


def test_protected_routes_need_the_bearer_token(tmp_path) -> None:
    client = _app(tmp_path, api_token="s3cret")

    assert client.get("/results/jira").status_code == 401
    assert client.get("/results/jira", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/results/jira", headers={"Authorization": "Basic s3cret"}).status_code == 401
    assert client.get("/results/jira", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_no_token_configured_fails_closed(tmp_path) -> None:
    assert _app(tmp_path).get("/results/jira").status_code == 503
    assert _app(tmp_path, api_token="").post("/sync/jira").status_code == 503


def test_auth_can_be_disabled_explicitly(tmp_path) -> None:
    assert _app(tmp_path, auth_disabled=True).get("/results/jira").status_code == 200


def test_missing_app_state_is_a_clear_503(tmp_path) -> None:
    client = _app(tmp_path, auth_disabled=True)  # sync_service was never set on app.state

    response = client.post("/sync/jira")

    assert response.status_code == 503
    assert "sync_service" in response.json()["detail"]

    client.app.state.sync_service = None
    assert client.post("/sync/jira").status_code == 503


async def test_audit_writer_does_not_raise_on_non_json_details() -> None:
    event = AuditEvent(
        source="jira", action="sync", status="failed", at=datetime.now(UTC), details={"error": RuntimeError("boom"), "obj": object()}
    )
    await StructlogAuditWriter().record(event)
