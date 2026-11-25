from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.results import router


def _client(output_dir) -> TestClient:
    app = FastAPI()
    app.state.output_dir = str(output_dir)
    app.include_router(router)
    return TestClient(app)


def _write_run(output_dir, run_id: str) -> None:
    directory = output_dir / "jira"
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "jira",
        "status": "success",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:01Z",
        "documents_count": 1,
        "cursor": None,
        "errors": [],
        "documents": [{"source_object_id": "ABC-1"}],
    }
    (directory / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_list_runs_returns_summaries_without_documents(tmp_path) -> None:
    _write_run(tmp_path, "20260101T000001")
    response = _client(tmp_path).get("/results/jira")

    assert response.status_code == 200
    run = response.json()[0]
    assert run["run_id"] == "20260101T000001"
    assert run["documents_count"] == 1
    assert "documents" not in run


def test_get_run_returns_full_payload(tmp_path) -> None:
    _write_run(tmp_path, "20260101T000001")
    response = _client(tmp_path).get("/results/jira/20260101T000001")

    assert response.status_code == 200
    assert response.json()["documents"][0]["source_object_id"] == "ABC-1"


def test_unknown_source_is_404(tmp_path) -> None:
    assert _client(tmp_path).get("/results/notasource").status_code == 404


def test_missing_run_is_404(tmp_path) -> None:
    assert _client(tmp_path).get("/results/jira/does-not-exist").status_code == 404


def test_run_id_cannot_escape_source_folder(tmp_path) -> None:
    (tmp_path / "jira").mkdir()
    (tmp_path / "secret.json").write_text("{}", encoding="utf-8")
    assert _client(tmp_path).get("/results/jira/..%2F..%2Fsecret").status_code == 404
