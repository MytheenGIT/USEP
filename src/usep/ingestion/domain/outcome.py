"""One vocabulary for how a unit of ingestion work ended.

It is shared by the retry runtime (HTTP calls), the raw payload writer (objects) and the cursor
manager (batches), so a value produced by one is understood by the others.
"""

from __future__ import annotations

from enum import StrEnum


class Outcome(StrEnum):
    # An HTTP call, from `usep.ingestion.runtime.retry`.
    """How a unit of ingestion work ended."""

    OK = "ok"
    REJECTED = "rejected"
    DEAD_LETTER = "dead_letter"
    DEFERRED = "deferred"
    # An object landing, from `usep.ingestion.raw.writer`.
    WRITTEN = "written"
    SKIPPED_UNCHANGED = "skipped_unchanged"
    QUARANTINED = "quarantined"
    FAILED = "failed"
