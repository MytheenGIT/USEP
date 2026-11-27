"""Named codes for audit records and quarantine entries, instead of string literals.

The string values are part of the audit and quarantine record formats.
"""

from __future__ import annotations

from enum import StrEnum


class QuarantineReason(StrEnum):
    """Why an object was quarantined instead of stored."""

    SCHEMA = "Q-SCHEMA"
    PII = "Q-PII"
    SECRET = "Q-SECRET"  # noqa: S105 - a reason code, not a credential


class AuditAction(StrEnum):
    """The action recorded in an audit event for an object."""

    OBJECT_REJECTED = "object.rejected"
    OBJECT_FAILED = "object.failed"
    OBJECT_QUARANTINED = "object.quarantined"
    OBJECT_SKIPPED_UNCHANGED = "object.skipped_unchanged"
    OBJECT_IMPORTED = "object.imported"


class AuditStatus(StrEnum):
    """Whether an audited action succeeded."""

    OK = "ok"
    FAILED = "failed"


class RejectionReason(StrEnum):
    """Why a write request was rejected before any processing."""

    ENVELOPE = "envelope"


class AuditDetail(StrEnum):
    """Keys used in an audit event's `details`."""

    OBJECT_ID = "object_id"
    REASON = "reason"
    COUNTS = "counts"
    CONTENT_HASH = "content_hash"
    EXCEPTION_TYPE = "exception_type"
