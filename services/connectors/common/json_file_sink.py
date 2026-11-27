from __future__ import annotations

import json
from pathlib import Path

from common.sync_models import SyncResponse, SyncResult

SUMMARY_SUFFIX = ".summary.json"
# Fields copied from a run into its summary file; the results API lists runs from these.
SUMMARY_FIELDS = ("source", "status", "started_at", "finished_at", "documents_count", "errors")


class JsonFileSink:
    """Writes each sync result to ``<output_dir>/<source>/<run_id>.json``.

    ``run_id`` is the run's finish time as ``YYYYMMDDTHHMMSSffffff`` (UTC,
    zero-padded). A small ``<run_id>.summary.json`` is written next to it so
    run listings never have to parse the documents.

    Temporary local store until Postgres persistence is available.
    """

    def __init__(self, output_dir: str) -> None:
        self._output_dir = Path(output_dir)

    def write(self, result: SyncResult) -> Path:
        directory = self._output_dir / result.source.value
        directory.mkdir(parents=True, exist_ok=True)
        run_id = f"{result.finished_at:%Y%m%dT%H%M%S%f}"
        path = directory / f"{run_id}.json"
        payload = SyncResponse.from_result(result, include_documents=True).model_dump(mode="json")
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        summary = {field: payload[field] for field in SUMMARY_FIELDS}
        (directory / f"{run_id}{SUMMARY_SUFFIX}").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        return path
