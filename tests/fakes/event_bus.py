from __future__ import annotations

from usep.ingestion.domain.events import RawObjectPublished


class InMemoryEventBus:
    """Fake `EventPublisherPort`, with idempotency by `event_id` (D1). Never
    imported from production code."""

    def __init__(self) -> None:
        self.published: list[RawObjectPublished] = []
        self._seen_event_ids: set[object] = set()
        self.fail_next: bool = False

    async def publish_raw(self, event: RawObjectPublished) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated publish failure")
        if event.event_id in self._seen_event_ids:
            return  # idempotent: already published
        self._seen_event_ids.add(event.event_id)
        self.published.append(event)
