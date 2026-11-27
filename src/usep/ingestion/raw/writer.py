"""The raw payload writer: `write(source, source_object_id, raw_payload) -> WriteResult`.

The three-argument signature has no room for `object_type`, `scope_id`, or
`checkpoint`, which the write algorithm needs (object-key format, the published
event). The caller passes them in `raw_payload["_usep"]`:
`{"object_type": str, "scope_id": str, "checkpoint": str}`, plus optional `source_version`,
`extracted_at` and `acl` (the source's permission attributes), which go on the published event
and not into the stored object. This key is stripped
before canonicalizing/hashing, so a metadata-only change never bumps the content
hash. `tenant_id` and `run_id` are bound at construction, not passed per call.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from usep.core.clock import Clock
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
from usep.ingestion.sensitive.detector import payload_text

SCHEMA_VERSION = "1.0"
_ENVELOPE_KEY = "_usep"
_ENVELOPE_REQUIRED_FIELDS = ("object_type", "scope_id", "checkpoint")

_EVENT_ID_NAMESPACE = uuid.UUID("3f4b8e2a-7d1c-4e9a-9c2b-5a6d8f1e0b3c")


def _derive_event_id(
    tenant_id: uuid.UUID, source: str, object_type: str, object_id: str, digest: str
) -> uuid.UUID:
    """Deterministic from the object's natural key, so a retried publish after an
    ack was lost reuses the same `event_id` rather than minting a new one."""
    return uuid.uuid5(_EVENT_ID_NAMESPACE, f"{tenant_id}:{source}:{object_type}:{object_id}:{digest}")


class EnvelopeError(ValueError):
    """Raised when `raw_payload["_usep"]` is missing or incomplete."""


def _extract_envelope(raw_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    envelope = raw_payload.get(_ENVELOPE_KEY)
    if not isinstance(envelope, dict):
        raise EnvelopeError(f"raw_payload is missing the {_ENVELOPE_KEY!r} envelope")
    missing = [f for f in _ENVELOPE_REQUIRED_FIELDS if not envelope.get(f)]
    if missing:
        raise EnvelopeError(f"{_ENVELOPE_KEY!r} envelope is missing required field(s): {missing}")
    stripped = {k: v for k, v in raw_payload.items() if k != _ENVELOPE_KEY}
    return stripped, envelope


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

    async def write(self, source: str, source_object_id: str, raw_payload: dict[str, Any]) -> WriteResult:
        """Returns a `WriteResult` (written, skipped_unchanged, quarantined or failed);
        never raises for a content- or storage-level failure (one object's failure
        never fails the run) — only `EnvelopeError` is raised, for a caller
        contract violation (`_usep` missing/incomplete), not a data-quality one.
        The caller must treat `failed` as unresolved and not move its cursor past it
        (LLD Table 1: checkpoint only after publish is acknowledged).
        """
        now = self._clock.now()
        try:
            stripped, envelope = _extract_envelope(raw_payload)
        except EnvelopeError:
            await self._audit.record(
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
                object_type=envelope["object_type"],
                scope_id=envelope["scope_id"],
                checkpoint=envelope["checkpoint"],
                raw_payload=stripped,
                envelope=envelope,
            )
        except Exception as exc:  # noqa: BLE001 - one object's failure never fails the run
            with contextlib.suppress(Exception):  # a broken audit sink must not hide the failure itself
                await self._audit.record(
                    AuditEvent(
                        source=source,
                        action="object.failed",
                        status="failed",
                        at=now,
                        details={"object_id": source_object_id, "exception_type": type(exc).__name__},
                    )
                )
            return WriteResult(Outcome.FAILED, reason=type(exc).__name__)

        return result

    async def _write(
        self,
        *,
        now: Any,
        source: str,
        object_id: str,
        object_type: str,
        scope_id: str,
        checkpoint: str,
        raw_payload: dict[str, Any],
        envelope: dict[str, Any],
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
        detection = self._detect(payload_text(raw_payload))
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
        if ref is not None and ref.published_at is not None:
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

        aad = key.encode("utf-8") + str(tenant_id).encode("utf-8")
        just_inserted = False
        if ref is None:
            # Step 5: generate a data key and wrap it. The index row is written FIRST and holds the
            # wrapped key, so the key an object was encrypted with can never be lost or overwritten
            # by a crash or by a second writer racing on the same object.
            data_key = generate_data_key()
            wrapped_dek, kek_id = await self._key_store.wrap(tenant_id, data_key)
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
            )
            just_inserted = await self._raw_index.insert_if_absent(new_ref)
            if just_inserted:
                ref = new_ref
            else:  # another writer got there first: use its row and its key
                ref = await self._raw_index.find(tenant_id, source, object_type, object_id, digest)
        if ref is None or ref.wrapped_dek is None:
            raise RuntimeError("raw object was erased or its index row is missing")
        if not just_inserted:
            data_key = await self._key_store.unwrap(tenant_id, ref.wrapped_dek, ref.kek_id)

        # Step 6: put the ciphertext, unless it is already there (a retry after a crash, or a racing
        # writer). Any writer encrypts with the key in the index row, so every copy decrypts.
        if just_inserted or not await self._object_store.exists(key):
            await self._object_store.put(key, pack(encrypt(canonical, data_key, aad=aad)))

        # Step 7: publish the reference-only event. event_id is deterministic, so a
        # retried publish after a lost ack reuses the same idempotency key.
        event = RawObjectPublished(
            event_id=_derive_event_id(tenant_id, source, object_type, object_id, digest),
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
            source_version=envelope.get("source_version"),
            extracted_at=envelope.get("extracted_at"),
            source_acl=envelope.get("acl") or {},
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
