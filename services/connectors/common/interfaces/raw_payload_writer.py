"""Contract for the Raw Payload Writer.

Ownership: implemented elsewhere (the real implementation persists raw
payloads to the S3-backed raw store). This module only defines the
interface and a logging-only default so the ingestion service is runnable
standalone. The default never writes to S3 and must be replaced before
this runs anywhere shared.
"""

from __future__ import annotations

from typing import Any, Protocol

import structlog

logger = structlog.get_logger(__name__)


class RawPayloadWriter(Protocol):
    """Persists a raw source payload out-of-band and returns a storage reference."""

    async def write(self, source: str, source_object_id: str, raw_payload: dict[str, Any]) -> str:
        """Persist ``raw_payload`` and return an opaque storage URI (e.g. an S3 key)."""
        ...


class NullRawPayloadWriter:
    """Default that only logs. Does not write to S3 or anywhere else."""

    async def write(self, source: str, source_object_id: str, raw_payload: dict[str, Any]) -> str:
        logger.debug("raw_payload_writer.noop", source=source, source_object_id=source_object_id)
        return f"noop://{source}/{source_object_id}"
