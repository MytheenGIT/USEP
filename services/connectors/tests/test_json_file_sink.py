from __future__ import annotations

import json

import pytest

from common.json_file_sink import JsonFileSink
from common.source_document import SourceType
from common.sync_models import SyncResult, SyncStatus
from datetime import UTC, datetime
from tests.conftest import make_source_document


@pytest.mark.asyncio
async def test_json_sink_writes_result_to_source_folder(tmp_path) -> None:
    now = datetime.now(UTC)
    result = SyncResult(
        source=SourceType.JIRA,
        status=SyncStatus.SUCCESS,
        started_at=now,
        finished_at=now,
        documents=[make_source_document()],
        cursor="2026-01-01",
    )

    path = JsonFileSink(str(tmp_path)).write(result)

    assert path.parent == tmp_path / "jira"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["documents_count"] == 1
    assert payload["documents"][0]["source_object_id"] == "ABC-1"
