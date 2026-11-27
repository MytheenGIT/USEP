"""Bus consumer for the fabric writer: reads `entity.<domain>` and `retraction`, commits each event, then the offset."""
from __future__ import annotations

from usep.fabric.writer import FabricWriter
from usep.ports.event_bus import EventBus, consume

GROUP = "fabric-writer"


class FabricConsumer:
    def __init__(self, bus: EventBus, writer: FabricWriter, domains: tuple[str, ...], group: str = GROUP) -> None:
        self._bus, self._writer, self._group = bus, writer, group
        self._topics = tuple(f"entity.{d}" for d in domains) + ("retraction",)

    def run_once(self, limit: int = 100) -> int:
        """Handle what is waiting on every topic. A storage error stops here and re-raises, so that event is delivered
        again; a bad event is parked by the writer and does not stop the consumer."""
        return sum(consume(self._bus, t, self._group, self._writer.handle, limit) for t in self._topics)
