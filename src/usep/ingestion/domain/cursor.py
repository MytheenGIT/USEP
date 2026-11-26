"""`SyncCursor`: the sync position for one (tenant, source_system, scope, lane)
(section 5.4; LLD §2.1). The cursor's own encoding (`cursor_type`, `cursor_value`)
is opaque to this layer — each source supplies its own meaning for it in the
connector phase; this phase only persists and version-checks it generically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

Lane = Literal["live", "backfill"]


@dataclass(frozen=True, slots=True)
class CursorKey:
    tenant_id: UUID
    source_system: str
    scope_id: str
    lane: Lane


@dataclass(frozen=True, slots=True)
class SyncCursor:
    key: CursorKey
    cursor_value: str | None
    cursor_type: str
    overlap_seconds: int
    updated_at: datetime
    version: int
