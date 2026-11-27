"""Publishes raw.<source> events to the S3 event bus (ADR-19, proposed).

Same object layout and envelope as usep.adapters.s3.event_bus, which is the consume side:
    <prefix>/raw.<source>/p<NNN>/<event_id>.json     partition = crc32(tenant_id:key) mod N, key = source_ref
Events for one object stay in one partition and sort in creation order (UUID v7). Conditional put makes a retry a no-op.
"""
from __future__ import annotations

import asyncio
import json
import zlib
from typing import Any

from common.ids import uuid7
from common.interfaces.raw_event_publisher import RawEvent
from common.s3._errors import is_precondition_failed

SCHEMA_VERSION = 1


class S3RawEventPublisher:
    def __init__(self, client: Any, bucket: str, tenant_id: str, prefix: str = "bus", partitions: int = 16) -> None:
        if not tenant_id:
            raise ValueError("tenant_id is required on every event (ADR-10)")
        self._s3, self._bucket, self._tenant = client, bucket, tenant_id
        self._prefix, self._partitions = prefix.strip("/"), partitions

    async def publish(self, event: RawEvent) -> None:
        topic = f"raw.{event.source}"
        event_id = str(uuid7())
        envelope = {
            "event_id": event_id, "topic": topic, "key": event.source_ref, "tenant_id": self._tenant,
            "type": "raw.snapshot_written", "schema_version": SCHEMA_VERSION,
            "occurred_at": event.retrieved_at.astimezone().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "payload": event.model_dump(mode="json"), "headers": {},
        }
        part = zlib.crc32(f"{self._tenant}:{event.source_ref}".encode()) % self._partitions
        key = f"{self._prefix}/{topic}/p{part:03d}/{event_id}.json"
        await asyncio.to_thread(self._put, key, json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode())

    def _put(self, key: str, body: bytes) -> None:
        try:
            self._s3.put_object(Bucket=self._bucket, Key=key, Body=body, ContentType="application/json",
                                IfNoneMatch="*")
        except Exception as exc:  # noqa: BLE001
            if not is_precondition_failed(exc):
                raise
