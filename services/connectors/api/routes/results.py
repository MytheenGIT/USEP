"""Read endpoints over saved sync results, so a UI can list runs and load their documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from common.sync_models import SyncStatus

router = APIRouter(prefix="/results", tags=["results"])

KNOWN_SOURCES = {"jira", "gitlab", "confluence", "figma"}


def get_output_dir(request: Request) -> Path:
    return Path(request.app.state.output_dir)


def _check_source(source: str) -> None:
    if source not in KNOWN_SOURCES:
        raise HTTPException(status_code=404, detail=f"Unknown source '{source}'")


@router.get("/{source}")
async def list_runs(source: str, output_dir: Path = Depends(get_output_dir)) -> list[dict[str, Any]]:
    """Summary of every saved run for a source, newest first. Documents are not included."""
    _check_source(source)
    directory = output_dir / source
    if not directory.exists():
        return []

    runs: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        payload = json.loads(path.read_text(encoding="utf-8"))
        runs.append(
            {
                "run_id": path.stem,
                "source": payload["source"],
                "status": payload["status"],
                "started_at": payload["started_at"],
                "finished_at": payload["finished_at"],
                "documents_count": payload["documents_count"],
                "errors": payload["errors"],
            }
        )
    return runs


@router.get("/{source}/{run_id}")
async def get_run(source: str, run_id: str, output_dir: Path = Depends(get_output_dir)) -> dict[str, Any]:
    """Full saved result for one run, including every document."""
    _check_source(source)
    path = output_dir / source / f"{run_id}.json"
    if not path.is_file() or path.resolve().parent != (output_dir / source).resolve():
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found for source '{source}'")
    return json.loads(path.read_text(encoding="utf-8"))
