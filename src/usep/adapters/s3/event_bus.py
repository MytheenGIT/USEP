"""S3 adapter for the event bus port (ADR-19, proposed).

Layout, all under one bucket and prefix (config keys bus.s3_bucket, bus.s3_prefix):

    <prefix>/<topic>/p<NNN>/<event_id>.json          one object per event, never overwritten
    <prefix>/_offsets/<topic>/<group>/p<NNN>.json    a consumer group's committed position

- Partition = crc32(tenant_id:key) mod N, so every event for one key lands in one partition.
- event_id is a UUID v7, and S3 lists keys in lexical order, so a listing is the order of creation.
  Per-key ordering therefore holds across producers whose clocks agree; ordering is not guaranteed across keys.
- Replay is a listing from the start (offset reset), which also serves a rebuild of a projection.
- Writes use a conditional put (If-None-Match: *) so a retry of the same event is a no-op, not a second copy.
- Latency is a polling interval, not a push. Suitable for the pilot's batch volumes; it is a trade-off made in ADR-19.

The S3 client is passed in (boto3 `client("s3")` or any object with the same methods). Credentials come from the
workload identity, never from this code or from Git.
"""
from __future__ import annotations

import json
import zlib
from typing import Any, Mapping

from usep.core.errors import EventBusError
from usep.core.ids import utc_now_iso, uuid7
from usep.ports.event_bus import Delivery, Event, SchemaRegistry


def _is_missing(exc: Exception) -> bool:
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
    return code in {"NoSuchKey", "404", "NotFound"}


def _is_precondition_failed(exc: Exception) -> bool:
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
    return code in {"PreconditionFailed", "412", "ConditionalRequestConflict"}


class S3EventBus:
    def __init__(self, client: Any, bucket: str, registry: SchemaRegistry, prefix: str = "bus",
                 partitions: int = 16) -> None:
        if partitions < 1:
            raise ValueError("partitions must be at least 1")
        self._s3, self._bucket, self._registry = client, bucket, registry
        self._prefix, self._partitions = prefix.strip("/"), partitions

    # ------------------------------------------------------------ keys
    def _partition(self, tenant_id: str, key: str) -> int:
        return zlib.crc32(f"{tenant_id}:{key}".encode()) % self._partitions

    def _event_prefix(self, topic: str, partition: int) -> str:
        return f"{self._prefix}/{topic}/p{partition:03d}/"

    def _offset_key(self, topic: str, group: str, partition: int) -> str:
        return f"{self._prefix}/_offsets/{topic}/{group}/p{partition:03d}.json"

    # ------------------------------------------------------------ produce
    def publish(self, topic: str, key: str, type: str, tenant_id: str, payload: Mapping[str, Any],
                headers: Mapping[str, str] | None = None) -> Event:
        if not tenant_id:
            raise EventBusError("tenant_id is required on every event (ADR-10)")
        if not key:
            raise EventBusError("an ordering key is required")
        version = self._registry.current_version(topic)
        self._registry.validate(topic, version, payload)            # an invalid event never reaches the bus
        event = Event(str(uuid7()), topic, key, tenant_id, type, version, utc_now_iso(), dict(payload),
                      dict(headers or {}))
        self._put_event(event)
        return event

    def _put_event(self, event: Event) -> None:
        part = self._partition(event.tenant_id, event.key)
        body = json.dumps(event.__dict__, sort_keys=True, separators=(",", ":")).encode()
        try:
            self._s3.put_object(Bucket=self._bucket, Key=f"{self._event_prefix(event.topic, part)}{event.event_id}.json",
                                Body=body, ContentType="application/json", IfNoneMatch="*")
        except Exception as exc:                                   # noqa: BLE001 - botocore ClientError
            if _is_precondition_failed(exc):
                return                                             # the same event is already stored
            raise EventBusError(f"publish to {event.topic} failed: {exc}") from exc

    # ------------------------------------------------------------ consume
    def _position(self, topic: str, group: str, partition: int) -> str | None:
        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=self._offset_key(topic, group, partition))
        except Exception as exc:                                   # noqa: BLE001
            if _is_missing(exc):
                return None
            raise EventBusError(f"read offset failed: {exc}") from exc
        return json.loads(obj["Body"].read())["position"]

    def poll(self, topic: str, group: str, limit: int = 100) -> list[Delivery]:
        """Next undelivered events, partition by partition, each partition in order. Reads, does not commit."""
        out: list[Delivery] = []
        for part in range(self._partitions):
            if len(out) >= limit:
                break
            prefix = self._event_prefix(topic, part)
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix, "MaxKeys": limit - len(out)}
            pos = self._position(topic, group, part)
            if pos:
                kwargs["StartAfter"] = pos
            for item in self._s3.list_objects_v2(**kwargs).get("Contents", []):
                raw = self._s3.get_object(Bucket=self._bucket, Key=item["Key"])["Body"].read()
                out.append(Delivery(Event(**json.loads(raw)), part, item["Key"]))
        return out

    def commit(self, group: str, delivery: Delivery) -> None:
        """Record that this event is handled. The position only moves forward."""
        topic, part = delivery.event.topic, delivery.partition
        current = self._position(topic, group, part)
        if current and current >= delivery.position:
            return
        self._s3.put_object(Bucket=self._bucket, Key=self._offset_key(topic, group, part),
                            Body=json.dumps({"position": delivery.position}).encode(),
                            ContentType="application/json")

    def reset(self, topic: str, group: str) -> None:
        """Replay from the start for one group: remove its offsets."""
        for part in range(self._partitions):
            self._s3.delete_object(Bucket=self._bucket, Key=self._offset_key(topic, group, part))
