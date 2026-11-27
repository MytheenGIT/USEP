from __future__ import annotations

from uuid import uuid4

import pytest
from tests.fakes.cursor_store import InMemoryCursorStore

from usep.ingestion.cursor.cursor_manager import CursorManager, effective_cursor
from usep.ingestion.domain.outcome import Outcome
from usep.ingestion.runtime.retry import Outcome as RetryOutcome


def test_timestamp_cursor_is_moved_back_by_the_overlap() -> None:
    assert effective_cursor("2026-01-01T00:10:00Z", 300) == "2026-01-01T00:05:00+00:00"


@pytest.mark.parametrize("opaque", ["abc123def", "20260101", "12345678"])
def test_opaque_cursor_is_returned_unchanged(opaque: str) -> None:
    assert effective_cursor(opaque, 300) == opaque


def test_no_cursor_means_a_full_sync() -> None:
    assert effective_cursor(None, 300) is None


@pytest.mark.asyncio
async def test_batch_starts_from_the_stored_cursor_minus_overlap() -> None:
    store = InMemoryCursorStore(uuid4())
    await store.set_cursor("jira", "2026-01-01T00:10:00Z")

    batch = await CursorManager(store, overlap_seconds=300).start_batch("jira")

    assert batch.fetch_from == "2026-01-01T00:05:00+00:00"


@pytest.mark.asyncio
async def test_cursor_advances_when_every_outcome_is_resolved() -> None:
    store = InMemoryCursorStore(uuid4())
    manager = CursorManager(store)
    batch = await manager.start_batch("jira")

    await manager.advance(
        batch, "c2", [Outcome.WRITTEN, Outcome.SKIPPED_UNCHANGED, Outcome.QUARANTINED, Outcome.DEFERRED]
    )

    assert await store.get_cursor("jira") == "c2"


@pytest.mark.asyncio
async def test_cursor_does_not_advance_past_a_failed_object() -> None:
    store = InMemoryCursorStore(uuid4())
    manager = CursorManager(store)
    batch = await manager.start_batch("jira")

    with pytest.raises(ValueError, match="failed"):
        await manager.advance(batch, "c2", [Outcome.WRITTEN, Outcome.FAILED])

    assert await store.get_cursor("jira") is None


@pytest.mark.asyncio
async def test_a_deferred_retry_result_lets_the_cursor_advance() -> None:
    store = InMemoryCursorStore(uuid4())
    manager = CursorManager(store)
    batch = await manager.start_batch("jira")

    await manager.advance(batch, "c2", [RetryOutcome.DEFERRED])

    assert await store.get_cursor("jira") == "c2"
