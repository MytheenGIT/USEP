from __future__ import annotations

from uuid import uuid4

import pytest
from tests.fakes.cursor_store import InMemoryCursorStore

from usep.ingestion.cursor.manager import CursorManager


@pytest.mark.asyncio
async def test_cursor_is_per_scope_and_lane_with_overlap() -> None:
    manager = CursorManager(InMemoryCursorStore(uuid4()), overlap_seconds=300)

    batch = await manager.start_batch("jira", "project = A")
    assert batch.key == "jira:project = A:live" and batch.fetch_from is None and batch.cursor is None

    await manager.advance(batch, "2026-01-01T00:10:00+00:00", ["written"])

    same = await manager.start_batch("jira", "project = A")
    assert same.cursor == "2026-01-01T00:10:00+00:00"  # stored value, untouched
    assert same.fetch_from == "2026-01-01T00:05:00+00:00"  # minus the 300 s overlap
    assert (await manager.start_batch("jira", "project = B")).cursor is None
    assert (await manager.start_batch("jira", "project = A", "backfill")).cursor is None


@pytest.mark.asyncio
async def test_cursor_does_not_advance_past_an_unresolved_object() -> None:
    manager = CursorManager(InMemoryCursorStore(uuid4()))
    batch = await manager.start_batch("gitlab", "g/p")

    with pytest.raises(ValueError):
        await manager.advance(batch, "2026-01-01T00:00:00+00:00", ["written", "failed"])

    assert (await manager.start_batch("gitlab", "g/p")).cursor is None
