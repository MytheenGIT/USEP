"""Contract for publishing a raw event (C-03 topic ``raw.<family>``) after a snapshot is durable.

The event carries references, never the payload: source_ref, snapshot_ref, checksum, source version and event time.
Optionally also the scope, the source's own updated time and the harvested ACL attributes (small metadata, not content).
Consumers (C-02 acquisition workers) read the snapshot from the raw store. The default only logs.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


class RawEvent(BaseModel):
    source: str                 # jira | gitlab | confluence | figma. Also the topic family: raw.<source>
    source_type: str            # object kind: issue, merge_request, page, ...
    source_ref: str             # stable id of the object in its source (source_object_id)
    source_url: str
    snapshot_ref: str           # where the immutable raw snapshot lives. Must be durable before publish.
    checksum: str               # sha256 of the canonical raw payload
    retrieved_at: datetime
    # Optional, add-only (schema v1 stays compatible). The connector harvested these next to the object; the
    # pipeline turns acl into labels and chunk-level access scopes.
    scope: str = ""
    source_version: str | None = None
    acl: dict[str, Any] = {}


class RawEventPublisher(Protocol):
    async def publish(self, event: RawEvent) -> None:
        """Publish one raw event. Returns only after the bus has acknowledged it, or raises."""
        ...

    async def publish_tombstone(self, source: str, source_id: str, scope: str, reason: str) -> None:
        """Announce that an object has been deleted at (or is no longer visible from) its source."""
        ...


class NullRawEventPublisher:
    """Default that only logs. Nothing reaches a bus."""

    async def publish(self, event: RawEvent) -> None:
        logger.debug("raw_event_publisher.noop", source=event.source, source_ref=event.source_ref)

    async def publish_tombstone(self, source: str, source_id: str, scope: str, reason: str) -> None:
        logger.debug("raw_event_publisher.tombstone_noop", source=source, source_id=source_id)
