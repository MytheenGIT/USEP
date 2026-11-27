from __future__ import annotations

import datetime as dt
from uuid import uuid4

import pytest
from tests.fakes.raw_index import InMemoryRawIndex

from usep.core.ids import new_id
from usep.ingestion.cursor.reconcile import reconcile_scope
from usep.ingestion.domain.raw_object import RawObjectRef

TENANT = uuid4()
T0 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
HOURS_21 = dt.timedelta(hours=21)


def _ref(object_id: str, content_hash: str, *, imported_at: dt.datetime = T0) -> RawObjectRef:
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
    )


async def _reconcile(index: InMemoryRawIndex, now: dt.datetime, listed: dict[str, str]) -> None:
    await reconcile_scope(
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
async def test_missing_and_stale_objects_are_reported_for_refetch() -> None:
    index = InMemoryRawIndex()
    await index.insert_if_absent(_ref("PROJ-1", "h1"))

    result = await reconcile_scope(
        index,
        tenant_id=TENANT,
        source="jira",
        scope_id="PROJ",
        source_ids=frozenset({"PROJ-1", "PROJ-2"}),
        source_versions={"PROJ-1": "h1-new", "PROJ-2": "h2"},
        now=T0,
    )

    assert result.missing == frozenset({"PROJ-2"})
    assert result.stale == frozenset({"PROJ-1"})


@pytest.mark.asyncio
async def test_object_is_not_stale_when_the_source_has_the_newest_stored_version() -> None:
    index = InMemoryRawIndex()
    await index.insert_if_absent(_ref("PROJ-1", "old", imported_at=T0))
    await index.insert_if_absent(_ref("PROJ-1", "new", imported_at=T0 + dt.timedelta(days=1)))

    result = await reconcile_scope(
        index,
        tenant_id=TENANT,
        source="jira",
        scope_id="PROJ",
        source_ids=frozenset({"PROJ-1"}),
        source_versions={"PROJ-1": "new"},
        now=T0 + dt.timedelta(days=2),
    )

    assert result.stale == frozenset()


@pytest.mark.asyncio
async def test_absent_object_is_marked_on_first_sight_and_kept() -> None:
    index = InMemoryRawIndex()
    await index.insert_if_absent(_ref("PROJ-1", "h1"))

    await _reconcile(index, T0, {})

    stored = _by_hash(index, "h1")
    assert stored.first_seen_extra_at == T0
    assert stored.tombstoned_at is None


@pytest.mark.asyncio
async def test_absent_object_is_not_tombstoned_before_the_waiting_period() -> None:
    index = InMemoryRawIndex()
    await index.insert_if_absent(_ref("PROJ-1", "h1"))
    await _reconcile(index, T0, {})

    await _reconcile(index, T0 + dt.timedelta(hours=19), {})

    assert _by_hash(index, "h1").tombstoned_at is None


@pytest.mark.asyncio
async def test_confirmed_absence_tombstones_every_stored_version() -> None:
    index = InMemoryRawIndex()
    await index.insert_if_absent(_ref("PROJ-1", "old", imported_at=T0))
    await index.insert_if_absent(_ref("PROJ-1", "new", imported_at=T0 + dt.timedelta(hours=1)))
    await _reconcile(index, T0 + dt.timedelta(hours=2), {})

    await _reconcile(index, T0 + dt.timedelta(hours=2) + HOURS_21, {})

    assert _by_hash(index, "old").tombstoned_at is not None
    assert _by_hash(index, "new").tombstoned_at is not None
    assert _by_hash(index, "old").wrapped_dek is None


@pytest.mark.asyncio
async def test_object_that_reappears_needs_a_fresh_two_sighting_confirmation() -> None:
    index = InMemoryRawIndex()
    await index.insert_if_absent(_ref("PROJ-1", "h1"))
    await _reconcile(index, T0, {})  # a source glitch hides the object
    await _reconcile(index, T0 + dt.timedelta(days=2), {"PROJ-1": "h1"})  # it is back

    await _reconcile(index, T0 + dt.timedelta(days=9), {})  # a later glitch hides it again

    stored = _by_hash(index, "h1")
    assert stored.tombstoned_at is None
    assert stored.first_seen_extra_at == T0 + dt.timedelta(days=9)
