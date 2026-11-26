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


def _write_summary_run(output_dir, run_id: str, started_at: str) -> None:
    directory = output_dir / "jira"
    directory.mkdir(parents=True, exist_ok=True)
    summary = {
        "source": "jira",
        "status": "success",
        "started_at": started_at,
        "finished_at": started_at,
        "documents_count": 2,
        "errors": [],
    }
    (directory / f"{run_id}.json").write_text(json.dumps({**summary, "documents": [{}, {}]}), encoding="utf-8")
    (directory / f"{run_id}.summary.json").write_text(json.dumps(summary), encoding="utf-8")


def test_corrupt_run_file_is_skipped_not_500(tmp_path) -> None:
    _write_run(tmp_path, "20260101T000001")
    (tmp_path / "jira" / "20260101T000002.json").write_text('{"source": "jira", "sta', encoding="utf-8")
    (tmp_path / "jira" / "20260101T000003.json").write_text('{"source": "jira"}', encoding="utf-8")

    response = _client(tmp_path).get("/results/jira")

    assert response.status_code == 200
    assert [run["run_id"] for run in response.json()] == ["20260101T000001"]
    assert response.headers["X-Total-Count"] == "1"
    assert _client(tmp_path).get("/results/jira/20260101T000002").status_code == 500


def test_runs_are_ordered_by_started_at_not_file_name(tmp_path) -> None:
    _write_summary_run(tmp_path, "aaa", "2026-03-01T00:00:00Z")
    _write_summary_run(tmp_path, "zzz", "2026-01-01T00:00:00Z")
    _write_summary_run(tmp_path, "mmm", "2026-02-01T00:00:00.500000Z")

    runs = _client(tmp_path).get("/results/jira").json()

    assert [run["run_id"] for run in runs] == ["aaa", "mmm", "zzz"]


def test_list_runs_is_paginated_and_uses_summary_files(tmp_path) -> None:
    for day in range(1, 6):
        _write_summary_run(tmp_path, f"run{day}", f"2026-01-0{day}T00:00:00Z")
    # A broken full file must not matter when its summary is readable.
    (tmp_path / "jira" / "run5.json").write_text("not json", encoding="utf-8")

    client = _client(tmp_path)
    page = client.get("/results/jira", params={"limit": 2, "offset": 1})

    assert [run["run_id"] for run in page.json()] == ["run4", "run3"]
    assert page.headers["X-Total-Count"] == "5"
    assert client.get("/results/jira", params={"limit": 0}).status_code == 422
    assert client.get("/results/jira", params={"limit": 201}).status_code == 422


def test_summary_file_is_not_served_as_a_run(tmp_path) -> None:
    _write_summary_run(tmp_path, "run1", "2026-01-01T00:00:00Z")
    assert _client(tmp_path).get("/results/jira/run1.summary").status_code == 404
