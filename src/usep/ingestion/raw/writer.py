"""The raw payload writer.

Matches the connectors branch's `RawPayloadWriter` Protocol exactly: `write(source,
source_object_id, raw_payload) -> str`.

That three-argument signature has no room for `object_type`, `scope_id`, or
`checkpoint`, which the write algorithm needs (object-key format, the published
event). Per agreed shape (option A, pending connector-owner confirmation — see
docs/plans/ASSUMPTIONS.md), the caller passes them in `raw_payload["_usep"]`:
`{"object_type": str, "scope_id": str, "checkpoint": str}`, plus an optional
`"source_version": str` (the source's own version of the object, used by reconciliation to
spot changes without re-fetching). This key is stripped
before canonicalizing/hashing, so a metadata-only change never bumps the content
hash. `tenant_id` and `run_id` are bound at construction, not passed per call.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NamedTuple

from usep.core.clock import Clock
from usep.core.errors import RawStorageError, UsepError, frames_only
from usep.core.ids import new_id
from usep.ingestion.domain.codes import (
    AuditAction,
    AuditDetail,
    AuditStatus,
    QuarantineReason,
    RejectionReason,
)
from usep.ingestion.domain.events import QuarantineRecord, RawObjectPublished
from usep.ingestion.domain.outcome import Outcome
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
FAILED_REF_PREFIX = "failed://"
QUARANTINED_REF_PREFIX = "quarantined://"
_ENVELOPE_KEY = "_usep"
_ENVELOPE_REQUIRED_FIELDS = ("object_type", "scope_id", "checkpoint")
_SOURCE_VERSION_KEY = "source_version"


class EnvelopeError(UsepError, ValueError):
    """Raised when `raw_payload["_usep"]` is missing or incomplete."""


class Envelope(NamedTuple):
    """The metadata a caller sends inside `raw_payload["_usep"]`."""

    object_type: str
    scope_id: str
    checkpoint: str
    source_version: str | None


def _require_ids(source: str, source_object_id: str) -> None:
    if not source or not source_object_id:
        raise EnvelopeError("source and source_object_id must be non-empty")


def _extract_envelope(raw_payload: dict[str, Any]) -> tuple[dict[str, Any], Envelope]:
    envelope = raw_payload.get(_ENVELOPE_KEY)
    if not isinstance(envelope, dict):
        raise EnvelopeError(f"raw_payload is missing the {_ENVELOPE_KEY!r} envelope")
    missing = [
        f for f in _ENVELOPE_REQUIRED_FIELDS if not isinstance(envelope.get(f), str) or not envelope[f]
    ]
    if missing:
        raise EnvelopeError(f"{_ENVELOPE_KEY!r} envelope needs non-empty string field(s): {missing}")
    source_version = envelope.get(_SOURCE_VERSION_KEY)
    if source_version is not None and (not isinstance(source_version, str) or not source_version):
        raise EnvelopeError(f"{_ENVELOPE_KEY!r} {_SOURCE_VERSION_KEY} must be a non-empty string when given")
    stripped = {k: v for k, v in raw_payload.items() if k != _ENVELOPE_KEY}
    return stripped, Envelope(
        envelope["object_type"], envelope["scope_id"], envelope["checkpoint"], source_version
    )


@dataclass(frozen=True, slots=True)
class WriteResult:
    """How one object write ended: the outcome, the stored key if any, and a reason."""

    outcome: Outcome
    object_key: str | None = None
    reason: str = ""


class RawPayloadWriter:
    """Stores source objects as encrypted raw evidence and publishes a reference event."""

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
        """Build the writer.

        Args:
            raw_index: Index of stored objects.
            object_store: Where encrypted bytes are kept.
            key_store: Wraps the per-object data keys.
            event_bus: Receives the reference-only event.
            quarantine: Holds objects that fail the sensitive-data scan.
            audit: Receives one audit event per object outcome.
            clock: Time source.
            tenant_id: Tenant every object belongs to.
            run_id: Run that produces the objects.
            detector: Scans text for sensitive data.
        """
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
        """Store one object; never raise for a content or storage failure.

        Matches the connectors branch's `RawPayloadWriter` protocol: it always returns a string, so
        one object's failure never fails the run. Only `EnvelopeError` is raised, for a caller
        contract violation (`_usep` missing or incomplete) rather than a data-quality problem.

        On quarantine or internal failure, returns a `quarantined://`/`failed://` sentinel reference
        rather than the real object key.
        """
        now = self._clock.now()
        try:
            _require_ids(source, source_object_id)
            stripped, envelope = _extract_envelope(raw_payload)
        except EnvelopeError:
            await self._audit_failure(
                AuditEvent(
                    source=source,
                    action=AuditAction.OBJECT_REJECTED,
                    status=AuditStatus.FAILED,
                    at=now,
                    details={
                        AuditDetail.OBJECT_ID: source_object_id,
                        AuditDetail.REASON: RejectionReason.ENVELOPE,
                    },
                )
            )
            raise

        try:
            result = await self._write(
                now=now,
                source=source,
                object_id=source_object_id,
                object_type=envelope.object_type,
                scope_id=envelope.scope_id,
                checkpoint=envelope.checkpoint,
                source_version=envelope.source_version,
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
                    action=AuditAction.OBJECT_FAILED,
                    status=AuditStatus.FAILED,
                    at=now,
                    details={
                        AuditDetail.OBJECT_ID: source_object_id,
                        AuditDetail.EXCEPTION_TYPE: type(exc).__name__,
                    },
                )
            )
            return f"{FAILED_REF_PREFIX}{type(exc).__name__}"

        if result.outcome == Outcome.QUARANTINED:
            return f"{QUARANTINED_REF_PREFIX}{result.reason}"
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
        source_version: str | None,
        raw_payload: dict[str, Any],
    ) -> WriteResult:
        # Steps 1-2: canonicalize, hash.
        try:
            canonical = canonicalize(raw_payload)
        except (TypeError, ValueError):
            return await self._quarantine_object(
                now, source, scope_id, object_type, object_id, QuarantineReason.SCHEMA
            )
        digest = content_hash(canonical)

        # Step 3: sensitive scan before any write or publish.
        detection = self._detect(canonical.decode("utf-8", errors="replace"))
        if detection.matched:
            reason = (
                QuarantineReason.PII if QuarantineReason.PII in detection.counts else QuarantineReason.SECRET
            )
            return await self._quarantine_object(
                now, source, scope_id, object_type, object_id, reason, detection.counts
            )

        # Step 4: dedupe on (tenant, source, object_type, object_id, content_hash).
        ref = await self._raw_index.find(self._tenant_id, source, object_type, object_id, digest)
        # shortcut: dedupe is per content hash, so content that reverts to an earlier version (A, B, A)
        # is skipped and downstream keeps B; upgrade by comparing with the object's newest row instead.
        if ref is not None and ref.tombstoned_at is None and ref.published_at is not None:
            return await self._skip_unchanged(ref, now, source, object_id, source_version)

        key = object_key(self._tenant_id, source, scope_id, object_type, object_id, digest)
        if ref is None or ref.tombstoned_at is not None:
            # A tombstoned row (key destroyed after a source deletion) is re-created, so an object
            # that comes back at the source becomes readable again.
            ref = await self._store_new_version(
                existing=ref,
                canonical=canonical,
                key=key,
                now=now,
                source=source,
                scope_id=scope_id,
                object_type=object_type,
                object_id=object_id,
                digest=digest,
                source_version=source_version,
            )

        await self._publish(
            ref,
            now=now,
            source=source,
            scope_id=scope_id,
            object_type=object_type,
            object_id=object_id,
            digest=digest,
            checkpoint=checkpoint,
        )
        return WriteResult(Outcome.WRITTEN, object_key=key)

    async def _quarantine_object(
        self,
        now: datetime,
        source: str,
        scope_id: str,
        object_type: str,
        object_id: str,
        reason: QuarantineReason,
        counts: dict[str, int] | None = None,
    ) -> WriteResult:
        """Quarantine an object: keep the reason and counts, audit it, and log it. Never the content."""
        await self._quarantine.quarantine(
            self._tenant_id,
            source,
            scope_id,
            object_type,
            object_id,
            QuarantineRecord(reason_code=reason, detector_counts=counts or {}),
        )
        details: dict[str, Any] = {AuditDetail.OBJECT_ID: object_id}
        log_fields: dict[str, Any] = {"source": source, "object_id": object_id, "reason_code": reason}
        if counts:
            details[AuditDetail.COUNTS] = counts
            log_fields["counts"] = counts
        await self._audit.record(
            AuditEvent(
                source=source,
                action=AuditAction.OBJECT_QUARANTINED,
                status=reason,
                at=now,
                details=details,
            )
        )
        logger.warning("object quarantined", extra=log_fields)
        return WriteResult(Outcome.QUARANTINED, reason=reason)

    async def _skip_unchanged(
        self, ref: RawObjectRef, now: datetime, source: str, object_id: str, source_version: str | None
    ) -> WriteResult:
        """Record that the content is already stored, keeping the source's version up to date."""
        if source_version is not None and ref.source_version != source_version:
            await self._raw_index.set_source_version(ref, source_version)
        await self._audit.record(
            AuditEvent(
                source=source,
                action=AuditAction.OBJECT_SKIPPED_UNCHANGED,
                status=AuditStatus.OK,
                at=now,
                details={AuditDetail.OBJECT_ID: object_id},
            )
        )
        return WriteResult(Outcome.SKIPPED_UNCHANGED, object_key=ref.object_key)

    async def _store_new_version(
        self,
        *,
        existing: RawObjectRef | None,
        canonical: bytes,
        key: str,
        now: datetime,
        source: str,
        scope_id: str,
        object_type: str,
        object_id: str,
        digest: str,
        source_version: str | None,
    ) -> RawObjectRef:
        """Encrypt and store the bytes, then insert (or revive) the index row; return the stored row."""
        tenant_id = self._tenant_id
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
            run_id=self._run_id,
            imported_at=now,
            published_at=None,
            wrapped_dek=wrapped_dek,
            kek_id=kek_id,
            event_id=new_id(),
            source_version=source_version,
        )
        store_row = self._raw_index.insert_if_absent if existing is None else self._raw_index.revive
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
        return stored

    async def _publish(
        self,
        ref: RawObjectRef,
        *,
        now: datetime,
        source: str,
        scope_id: str,
        object_type: str,
        object_id: str,
        digest: str,
        checkpoint: str,
    ) -> None:
        """Publish the reference-only event, mark the row published, and audit the import."""
        # Step 7: event_id is fixed per object (UUID v7, minted when the row is inserted or
        # revived), so a retried publish after a lost ack reuses the same idempotency key.
        event = RawObjectPublished(
            event_id=ref.event_id,
            schema_version=SCHEMA_VERSION,
            tenant_id=self._tenant_id,
            source=source,
            scope_id=scope_id,
            object_type=object_type,
            object_id=object_id,
            object_key=ref.object_key,
            content_hash=digest,
            run_id=self._run_id,
            checkpoint=checkpoint,
        )
        await self._event_bus.publish_raw(event)
        await self._raw_index.mark_published(ref)

        # Step 8: audit the import.
        await self._audit.record(
            AuditEvent(
                source=source,
                action=AuditAction.OBJECT_IMPORTED,
                status=AuditStatus.OK,
                at=now,
                details={AuditDetail.OBJECT_ID: object_id, AuditDetail.CONTENT_HASH: digest},
            )
        )
