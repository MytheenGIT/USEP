"""``EventPublisherPort`` that only logs the reference-only ``raw.<family>`` event.

DEVELOPMENT ONLY: nothing is published to Kafka. The HLD (D2) puts these events on the
``raw.<family>`` topic; the port and adapter are open item O-19 (ADR-037, not yet written).
Replace this before anything downstream is expected to consume the events.
"""

from __future__ import annotations

import structlog

from usep.ingestion.domain.events import RawObjectPublished

logger = structlog.get_logger(__name__)


class LogEventPublisher:
    async def publish_raw(self, event: RawObjectPublished) -> None:
        logger.info(
            "raw_object.published",
            event_id=str(event.event_id), source=event.source, scope_id=event.scope_id,
            object_type=event.object_type, object_id=event.object_id, object_key=event.object_key,
            content_hash=event.content_hash, run_id=str(event.run_id),
        )
