"""The raw payload writer. Matches the connectors branch's `RawPayloadWriter`
Protocol exactly: `write(source, source_object_id, raw_payload) -> str`.

That three-argument signature has no room for `object_type`, `scope_id`, or
`checkpoint`, which the write algorithm needs (object-key format, the published
event). Per agreed shape (option A, pending connector-owner confirmation — see
docs/plans/ASSUMPTIONS.md), the caller passes them in `raw_payload["_usep"]`:
`{"object_type": str, "scope_id": str, "checkpoint": str}`. This key is stripped
before canonicalizing/hashing, so a metadata-only change never bumps the content
hash. `tenant_id` and `run_id` are bound at construction, not passed per call.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from usep.core.clock import Clock
from usep.core.errors import RawStorageError, UsepError, frames_only
from usep.core.ids import new_id
from usep.ingestion.domain.events import QuarantineRecord, RawObjectPublished
from usep.ingestion.domain.raw_object import RawObjectRef, canonicalize, content_hash, object_key
from usep.ingestion.domain.sensitive import DetectionResult
from usep.ingestion.ports.audit import AuditEvent, AuditPort
from usep.ingestion.ports.event_bus import EventPublisherPort
from usep.ingestion.ports.key_store import KeyEncryptionPort
from usep.ingestion.ports.object_store import ObjectStorePort
from usep.ingestion.ports.quarantine import QuarantinePort
from usep.ingestion.ports.raw_index import RawIndexPort
from usep.ingestion.raw.crypto import encrypt, generate_data_key, pack
from usep.ingestion.sensitive.detector import detect as _default_detect

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"
_ENVELOPE_KEY = "_usep"
_ENVELOPE_REQUIRED_FIELDS = ("object_type", "scope_id", "checkpoint")


class EnvelopeError(UsepError, ValueError):
    """Raised when `raw_payload["_usep"]` is missing or incomplete."""


def _extract_envelope(raw_payload: dict[str, Any]) -> tuple[dict[str, Any], str, str, str]:
    envelope = raw_payload.get(_ENVELOPE_KEY)
    if not isinstance(envelope, dict):
        raise EnvelopeError(f"raw_payload is missing the {_ENVELOPE_KEY!r} envelope")
    missing = [
        f for f in _ENVELOPE_REQUIRED_FIELDS if not isinstance(envelope.get(f), str) or not envelope[f]
    ]
    if missing:
        raise EnvelopeError(f"{_ENVELOPE_KEY!r} envelope needs non-empty string field(s): {missing}")
    stripped = {k: v for k, v in raw_payload.items() if k != _ENVELOPE_KEY}
    return stripped, envelope["object_type"], envelope["scope_id"], envelope["checkpoint"]


class Outcome:
    WRITTEN = "written"
    SKIPPED_UNCHANGED = "skipped_unchanged"
    QUARANTINED = "quarantined"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WriteResult:
    outcome: str
    object_key: str | None = None
    reason: str = ""


class RawPayloadWriter:
    def __init__(
        self,
        raw_index: RawIndexPort,
        object_store: ObjectStorePort,
        key_store: KeyEncryptionPort,
        event_bus: EventPublisherPort,
        quarantine: QuarantinePort,
        audit: AuditPort,
        clock: Clock,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        detector: Callable[[str], DetectionResult] = _default_detect,
    ) -> None:
        self._raw_index = raw_index
        self._object_store = object_store
        self._key_store = key_store
        self._event_bus = event_bus
        self._quarantine = quarantine
        self._audit = audit
        self._clock = clock
        self._tenant_id = tenant_id
        self._run_id = run_id
        self._detect = detector

    async def write(self, source: str, source_object_id: str, raw_payload: dict[str, Any]) -> str:
        """Matches `RawPayloadWriter` exactly: always returns a string, never
        raises for a content- or storage-level failure (one object's failure
        never fails the run) — only `EnvelopeError` is raised, for a caller
        contract violation (`_usep` missing/incomplete), not a data-quality one.
        On quarantine or internal failure, returns a `quarantined://`/`failed://`
        sentinel reference rather than the real object key.
        """
        now = self._clock.now()
        try:
            stripped, object_type, scope_id, checkpoint = _extract_envelope(raw_payload)
        except EnvelopeError:
            await self._audit_failure(
                AuditEvent(
                    source=source,
                    action="object.rejected",
                    status="failed",
                    at=now,
                    details={"object_id": source_object_id, "reason": "envelope"},
                )
            )
            raise

        try:
            result = await self._write(
                now=now,
                source=source,
                object_id=source_object_id,
                object_type=object_type,
                scope_id=scope_id,
                checkpoint=checkpoint,
                raw_payload=stripped,
            )
        except Exception as exc:  # noqa: BLE001 - one object's failure never fails the run
            logger.error(
                "raw object write failed",
                extra={
                    "source": source,
                    "object_id": source_object_id,
                    "exception_type": type(exc).__name__,
                    "frames": frames_only(exc),
                },
            )
            await self._audit_failure(
                AuditEvent(
                    source=source,
                    action="object.failed",
                    status="failed",
                    at=now,
                    details={"object_id": source_object_id, "exception_type": type(exc).__name__},
                )
            )
            return f"failed://{type(exc).__name__}"

        if result.outcome == Outcome.QUARANTINED:
            return f"quarantined://{result.reason}"
        return result.object_key or ""

    async def _audit_failure(self, event: AuditEvent) -> None:
        """Audit a failure path. An audit outage must not replace the error being reported."""
        try:
            await self._audit.record(event)
        except Exception as exc:  # noqa: BLE001 - the write already failed and the run must go on
            logger.error(
                "audit record failed while reporting a failure",
                extra={
                    "action": event.action,
                    "exception_type": type(exc).__name__,
                    "frames": frames_only(exc),
                },
            )

    async def _write(
        self,
        *,
        now: datetime,
        source: str,
        object_id: str,
        object_type: str,
        scope_id: str,
        checkpoint: str,
        raw_payload: dict[str, Any],
    ) -> WriteResult:
        tenant_id = self._tenant_id
        run_id = self._run_id

        # Steps 1-2: canonicalize, hash.
        try:
            canonical = canonicalize(raw_payload)
        except (TypeError, ValueError):
            await self._quarantine.quarantine(
                tenant_id,
                source,
                scope_id,
                object_type,
                object_id,
                QuarantineRecord(reason_code="Q-SCHEMA", detector_counts={}),
            )
            await self._audit.record(
                AuditEvent(
                    source=source,
                    action="object.quarantined",
                    status="Q-SCHEMA",
                    at=now,
                    details={"object_id": object_id},
                )
            )
            return WriteResult(Outcome.QUARANTINED, reason="Q-SCHEMA")
        digest = content_hash(canonical)

        # Step 3: sensitive scan before any write or publish.
        detection = self._detect(canonical.decode("utf-8", errors="replace"))
        if detection.matched:
            reason_code = "Q-PII" if "Q-PII" in detection.counts else "Q-SECRET"
            await self._quarantine.quarantine(
                tenant_id,
                source,
                scope_id,
                object_type,
                object_id,
                QuarantineRecord(reason_code=reason_code, detector_counts=detection.counts),
            )
            await self._audit.record(
                AuditEvent(
                    source=source,
                    action="object.quarantined",
                    status=reason_code,
                    at=now,
                    details={"object_id": object_id, "counts": detection.counts},
                )
            )
            return WriteResult(Outcome.QUARANTINED, reason=reason_code)

        # Step 4: dedupe on (tenant, source, object_type, object_id, content_hash).
        ref = await self._raw_index.find(tenant_id, source, object_type, object_id, digest)
        if ref is not None and ref.tombstoned_at is None and ref.published_at is not None:
            await self._audit.record(
                AuditEvent(
                    source=source,
                    action="object.skipped_unchanged",
                    status="ok",
                    at=now,
                    details={"object_id": object_id},
                )
            )
            return WriteResult(Outcome.SKIPPED_UNCHANGED, object_key=ref.object_key)

        key = object_key(tenant_id, source, scope_id, object_type, object_id, digest)

        if ref is None or ref.tombstoned_at is not None:
            # A tombstoned row (key destroyed after a source deletion) is re-created below, so an
            # object that comes back at the source becomes readable again.
            # Step 5: generate a data key, encrypt, wrap.
            data_key = generate_data_key()
            aad = key.encode("utf-8") + str(tenant_id).encode("utf-8")
            encrypted = encrypt(canonical, data_key, aad=aad)
            wrapped_dek, kek_id = await self._key_store.wrap(tenant_id, data_key)

            # Step 6: put the ciphertext, mint event_id, insert the index row.
            await self._object_store.put(key, pack(encrypted))
            new_ref = RawObjectRef(
                tenant_id=tenant_id,
                source=source,
                object_type=object_type,
                object_id=object_id,
                content_hash=digest,
                scope_id=scope_id,
                object_key=key,
                byte_size=len(canonical),
                run_id=run_id,
                imported_at=now,
                published_at=None,
                wrapped_dek=wrapped_dek,
                kek_id=kek_id,
                event_id=new_id(),
            )
            store_row = self._raw_index.insert_if_absent if ref is None else self._raw_index.revive
            stored = await store_row(new_ref)
            if stored.wrapped_dek != wrapped_dek:
                # Lost an insert race. Our put may have overwritten the winner's ciphertext, but
                # the index holds the winner's wrapped key, so re-encrypt under that key.
                # shortcut: a crash between our put and the re-put leaves a blob the stored key
                # cannot decrypt; upgrade by inserting the row first and putting under its key.
                if stored.wrapped_dek is None:
                    raise RawStorageError("raw index row has no wrapped data key")
                stored_key = await self._key_store.unwrap(tenant_id, stored.wrapped_dek, stored.kek_id)
                await self._object_store.put(key, pack(encrypt(canonical, stored_key, aad=aad)))
            ref = stored

        # Step 7: publish the reference-only event. event_id is fixed per object
        # (UUID v7, minted when first inserted), so a retried publish after a lost
        # ack reuses the same idempotency key.
        event = RawObjectPublished(
            event_id=ref.event_id,
            schema_version=SCHEMA_VERSION,
            tenant_id=tenant_id,
            source=source,
            scope_id=scope_id,
            object_type=object_type,
            object_id=object_id,
            object_key=key,
            content_hash=digest,
            run_id=run_id,
            checkpoint=checkpoint,
        )
        await self._event_bus.publish_raw(event)
        await self._raw_index.mark_published(ref)

        # Step 8: audit the import.
        await self._audit.record(
            AuditEvent(
                source=source,
                action="object.imported",
                status="ok",
                at=now,
                details={"object_id": object_id, "content_hash": digest},
            )
        )
        return WriteResult(Outcome.WRITTEN, object_key=key)
