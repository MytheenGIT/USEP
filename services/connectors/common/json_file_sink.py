from __future__ import annotations

import json
from pathlib import Path

from common.sync_models import SyncResponse, SyncResult


class JsonFileSink:
    """Writes each sync result to ``<output_dir>/<source>/<timestamp>.json``.

    Temporary local store until Postgres persistence is available.
    """

    def __init__(self, output_dir: str) -> None:
        self._output_dir = Path(output_dir)

    def write(self, result: SyncResult) -> Path:
        directory = self._output_dir / result.source.value
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{result.finished_at:%Y%m%dT%H%M%S%f}.json"
        payload = SyncResponse.from_result(result, include_documents=True).model_dump(mode="json")
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
