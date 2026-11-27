from __future__ import annotations

import datetime as dt
import logging
from uuid import uuid4

import pytest
from tests.fakes.raw_index import InMemoryRawIndex

from usep.core.ids import new_id
from usep.ingestion.cursor.reconcile import reconcile_scope
from usep.ingestion.domain.raw_object import RawObjectRef

TENANT = uuid4()
T0 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
HOURS_21 = dt.timedelta(hours=21)
STILL_THERE = {"PROJ-KEEP": "kv"}  # keeps the scope's listing non-empty


def _ref(
    object_id: str,
    content_hash: str,
    *,
    imported_at: dt.datetime = T0,
    source_version: str | None = None,
) -> RawObjectRef:
    return RawObjectRef(
        tenant_id=TENANT,
        source="jira",
        object_type="issue",
        object_id=object_id,
        content_hash=content_hash,
        scope_id="PROJ",
        object_key=f"raw/{object_id}/{content_hash}.json",
        byte_size=1,
        run_id=uuid4(),
        imported_at=imported_at,
        published_at=imported_at,
        wrapped_dek=b"wrapped",
        kek_id="kek-1",
        event_id=new_id(),
        source_version=source_version,
    )


async def _index_with_keeper() -> InMemoryRawIndex:
    index = InMemoryRawIndex()
    await index.insert_if_absent(_ref("PROJ-KEEP", "k", source_version="kv"))
    return index


async def _reconcile(index: InMemoryRawIndex, now: dt.datetime, listed: dict[str, str]):
    return await reconcile_scope(
        index,
        tenant_id=TENANT,
        source="jira",
        scope_id="PROJ",
        source_ids=frozenset(listed),
        source_versions=listed,
        now=now,
    )


def _by_hash(index: InMemoryRawIndex, content_hash: str) -> RawObjectRef:
    return next(r for r in index.all_refs() if r.content_hash == content_hash)


@pytest.mark.asyncio
async def test_missing_and_changed_objects_are_reported_for_refetch() -> None:
    index = InMemoryRawIndex()
    await index.insert_if_absent(_ref("PROJ-1", "h1", source_version="2026-01-01T10:00:00Z"))

    result = await _reconcile(index, T0, {"PROJ-1": "2026-01-02T10:00:00Z", "PROJ-2": "x"})

    assert result.missing == frozenset({"PROJ-2"})
    assert result.stale == frozenset({"PROJ-1"})


@pytest.mark.asyncio
async def test_object_is_not_stale_when_the_source_version_is_unchanged() -> None:
    index = InMemoryRawIndex()
    await index.insert_if_absent(_ref("PROJ-1", "h1", source_version="2026-01-01T10:00:00Z"))

    result = await _reconcile(index, T0, {"PROJ-1": "2026-01-01T10:00:00Z"})

    assert result.stale == frozenset()


@pytest.mark.asyncio
async def test_object_with_no_recorded_source_version_counts_as_stale() -> None:
    index = InMemoryRawIndex()
    await index.insert_if_absent(_ref("PROJ-1", "h1"))

    result = await _reconcile(index, T0, {"PROJ-1": "v1"})

    assert result.stale == frozenset({"PROJ-1"})


@pytest.mark.asyncio
async def test_object_is_not_stale_when_the_source_has_the_newest_stored_version() -> None:
    index = InMemoryRawIndex()
    await index.insert_if_absent(_ref("PROJ-1", "old", imported_at=T0, source_version="v1"))
    await index.insert_if_absent(
        _ref("PROJ-1", "new", imported_at=T0 + dt.timedelta(days=1), source_version="v2")
    )

    result = await _reconcile(index, T0 + dt.timedelta(days=2), {"PROJ-1": "v2"})

    assert result.stale == frozenset()


@pytest.mark.asyncio
async def test_absent_object_is_marked_on_first_sight_and_kept() -> None:
    index = await _index_with_keeper()
    await index.insert_if_absent(_ref("PROJ-1", "h1"))

    await _reconcile(index, T0, STILL_THERE)

    stored = _by_hash(index, "h1")
    assert stored.first_seen_extra_at == T0
    assert stored.tombstoned_at is None


@pytest.mark.asyncio
async def test_absent_object_is_not_tombstoned_before_the_waiting_period() -> None:
    index = await _index_with_keeper()
    await index.insert_if_absent(_ref("PROJ-1", "h1"))
    await _reconcile(index, T0, STILL_THERE)

    await _reconcile(index, T0 + dt.timedelta(hours=19), STILL_THERE)

    assert _by_hash(index, "h1").tombstoned_at is None


@pytest.mark.asyncio
async def test_confirmed_absence_tombstones_every_stored_version() -> None:
    index = await _index_with_keeper()
    await index.insert_if_absent(_ref("PROJ-1", "old", imported_at=T0))
    await index.insert_if_absent(_ref("PROJ-1", "new", imported_at=T0 + dt.timedelta(hours=1)))
    await _reconcile(index, T0 + dt.timedelta(hours=2), STILL_THERE)

    await _reconcile(index, T0 + dt.timedelta(hours=2) + HOURS_21, STILL_THERE)

    assert _by_hash(index, "old").tombstoned_at is not None
    assert _by_hash(index, "new").tombstoned_at is not None
    assert _by_hash(index, "old").wrapped_dek is None
    assert _by_hash(index, "k").tombstoned_at is None


@pytest.mark.asyncio
async def test_object_that_reappears_needs_a_fresh_two_sighting_confirmation() -> None:
    index = await _index_with_keeper()
    await index.insert_if_absent(_ref("PROJ-1", "h1", source_version="v1"))
    await _reconcile(index, T0, STILL_THERE)  # a source glitch hides the object
    await _reconcile(index, T0 + dt.timedelta(days=2), {**STILL_THERE, "PROJ-1": "v1"})  # it is back

    await _reconcile(index, T0 + dt.timedelta(days=9), STILL_THERE)  # a later glitch hides it again

    stored = _by_hash(index, "h1")
    assert stored.tombstoned_at is None
    assert stored.first_seen_extra_at == T0 + dt.timedelta(days=9)


@pytest.mark.asyncio
async def test_an_empty_listing_never_marks_or_tombstones_anything(caplog: pytest.LogCaptureFixture) -> None:
    index = InMemoryRawIndex()
    for i in range(3):
        await index.insert_if_absent(_ref(f"PROJ-{i}", f"h{i}"))

    with caplog.at_level(logging.WARNING, logger="usep.ingestion.cursor.reconcile"):
        await _reconcile(index, T0, {})
        await _reconcile(index, T0 + dt.timedelta(days=2), {})

    assert all(r.tombstoned_at is None and r.first_seen_extra_at is None for r in index.all_refs())
    assert "reconcile skipped" in caplog.text


@pytest.mark.asyncio
async def test_an_empty_listing_for_an_empty_scope_is_not_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="usep.ingestion.cursor.reconcile"):
        result = await _reconcile(InMemoryRawIndex(), T0, {})

    assert result.missing == result.extra == result.stale == frozenset()
    assert caplog.text == ""
