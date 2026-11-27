"""`SyncCursor`: the sync position for one tenant, source, scope and lane.

See section 5.4 and LLD §2.1.

The cursor's own encoding (`cursor_type`, `cursor_value`) is opaque to this layer — each source
supplies its own meaning for it in the connector phase; this phase only persists and version-checks
it generically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Lane(StrEnum):
    """Which budget a sync runs on: live updates or historical backfill."""

    LIVE = "live"
    BACKFILL = "backfill"


@dataclass(frozen=True, slots=True)
class CursorKey:
    """Identifies one sync position: tenant, source system, scope and lane."""

    tenant_id: UUID
    source_system: str
    scope_id: str
    lane: Lane


@dataclass(frozen=True, slots=True)
class SyncCursor:
    """A saved sync position with its encoding, overlap and version."""

    key: CursorKey
    cursor_value: str | None
    cursor_type: str
    overlap_seconds: int
    updated_at: datetime
    version: int
