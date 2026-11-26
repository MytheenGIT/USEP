"""Read endpoints over saved sync results, so a UI can list runs and load their documents.

The handlers are plain ``def`` on purpose: they do blocking file I/O, and
FastAPI runs sync handlers in its threadpool instead of on the event loop.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.deps import get_output_dir
from common.json_file_sink import SUMMARY_FIELDS, SUMMARY_SUFFIX

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/results", tags=["results"])

KNOWN_SOURCES = {"jira", "gitlab", "confluence", "figma"}
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _check_source(source: str) -> None:
    if source not in KNOWN_SOURCES:
        raise HTTPException(status_code=404, detail=f"Unknown source '{source}'")


def _read_summary(directory: Path, run_id: str) -> dict[str, Any] | None:
    """Summary for one run, or None if its files are corrupt or unreadable.

    Reads the small ``<run_id>.summary.json`` written next to each run. Runs
    saved before summaries existed fall back to the full run file.
    """
    summary_path = directory / f"{run_id}{SUMMARY_SUFFIX}"
    path = summary_path if summary_path.is_file() else directory / f"{run_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {"run_id": run_id, **{field: payload[field] for field in SUMMARY_FIELDS}}
    except (json.JSONDecodeError, OSError, KeyError, TypeError) as exc:
        logger.warning("results.unreadable_run_file", path=str(path), error=str(exc))
        return None


def _started_at(summary: dict[str, Any]) -> datetime:
    """Sort key: the run's own ``started_at``, never the file name."""
    try:
        value = datetime.fromisoformat(str(summary["started_at"]).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@router.get("/{source}")
def list_runs(
    source: str,
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    output_dir: Path = Depends(get_output_dir),
) -> list[dict[str, Any]]:
    """Run summaries for a source, newest ``started_at`` first. Documents are not included.

    Paginated with ``limit`` and ``offset``; the ``X-Total-Count`` header has
    the number of readable runs. Corrupt or partial run files are skipped.
    """
    _check_source(source)
    directory = output_dir / source
    if not directory.is_dir():
        response.headers["X-Total-Count"] = "0"
        return []

    run_ids = {p.name[: -len(".json")] for p in directory.glob("*.json") if not p.name.endswith(SUMMARY_SUFFIX)}
    summaries = [s for s in (_read_summary(directory, run_id) for run_id in run_ids) if s is not None]
    summaries.sort(key=lambda s: (_started_at(s), s["run_id"]), reverse=True)

    response.headers["X-Total-Count"] = str(len(summaries))
    return summaries[offset : offset + limit]


@router.get("/{source}/{run_id}")
def get_run(source: str, run_id: str, output_dir: Path = Depends(get_output_dir)) -> dict[str, Any]:
    """Full saved result for one run, including every document."""
    _check_source(source)
    not_found = HTTPException(status_code=404, detail=f"Run '{run_id}' not found for source '{source}'")
    if not _RUN_ID.fullmatch(run_id):
        raise not_found
    path = output_dir / source / f"{run_id}.json"
    if not path.is_file() or path.resolve().parent != (output_dir / source).resolve():
        raise not_found
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("results.unreadable_run_file", path=str(path), error=str(exc))
        raise HTTPException(status_code=500, detail=f"Run '{run_id}' is saved but its file is unreadable.") from exc
