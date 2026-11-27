"""`EventPublisherPort`: publishes the reference-only raw-object event."""

from __future__ import annotations

from typing import Protocol

from usep.ingestion.domain.events import RawObjectPublished


class EventPublisherPort(Protocol):
    """Publishes reference-only events to the message bus."""

    async def publish_raw(self, event: RawObjectPublished) -> None:
        """Publishes `event`, keyed by `event.event_id` for idempotency."""
        ...
