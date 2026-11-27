"""Event bus port (C-03). Domain code depends on this module and imports no vendor SDK.

Contract (HLD 4.4 C-03): one ingestion contract, ordered per key, replayable, schemas registered per topic.
Delivery is at least once: a consumer commits its position after it has handled an event, so an event may be
handled twice after a crash. Consumers must be idempotent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from usep.core.errors import SchemaViolation


@dataclass(frozen=True)
class Event:
    event_id: str                    # UUID v7. Sorts in creation order, which is what gives per-key ordering.
    topic: str
    key: str                         # ordering key, for example an entity id or a tenant id
    tenant_id: str                   # in every event (ADR-10)
    type: str
    schema_version: int
    occurred_at: str                 # UTC ISO 8601, milliseconds
    payload: Mapping[str, Any]
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Delivery:
    event: Event
    partition: int
    position: str                    # opaque to callers; pass the Delivery back to commit()


class EventBus(Protocol):
    def publish(self, topic: str, key: str, type: str, tenant_id: str, payload: Mapping[str, Any],
                headers: Mapping[str, str] | None = None) -> Event: ...

    def poll(self, topic: str, group: str, limit: int = 100) -> list[Delivery]: ...

    def commit(self, group: str, delivery: Delivery) -> None: ...


class SchemaRegistry:
    """Minimal registry: per topic, the current version and the payload fields every event must carry.

    A new version may add optional fields only (backwards-compatible evolution, HLD 4.4 C-03).
    """

    def __init__(self) -> None:
        self._topics: dict[str, tuple[int, frozenset[str]]] = {}

    def register(self, topic: str, version: int, required: tuple[str, ...]) -> None:
        cur = self._topics.get(topic)
        if cur and (version <= cur[0] or not cur[1] <= set(required)):
            raise SchemaViolation(f"{topic}: version {version} is not a backwards-compatible evolution of {cur[0]}")
        self._topics[topic] = (version, frozenset(required))

    def validate(self, topic: str, schema_version: int, payload: Mapping[str, Any]) -> None:
        if topic not in self._topics:
            raise SchemaViolation(f"{topic}: no schema registered")
        version, required = self._topics[topic]
        if schema_version != version:
            raise SchemaViolation(f"{topic}: schema_version {schema_version}, registry holds {version}")
        missing = sorted(required - set(payload))
        if missing:
            raise SchemaViolation(f"{topic}: payload missing {', '.join(missing)}")

    def current_version(self, topic: str) -> int:
        if topic not in self._topics:
            raise SchemaViolation(f"{topic}: no schema registered")
        return self._topics[topic][0]


def consume(bus: EventBus, topic: str, group: str, handler: Callable[[Event], None], limit: int = 100) -> int:
    """Handle what is waiting, committing after each success. Stops at the first failure and re-raises it,
    so the failed event and everything after it is delivered again (at least once, order kept)."""
    n = 0
    for d in bus.poll(topic, group, limit):
        handler(d.event)
        bus.commit(group, d)
        n += 1
    return n
