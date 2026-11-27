"""One audit event type for the whole platform: the foundation's. ``AuditWriter`` is its port."""

from usep.ingestion.ports.audit import AuditEvent, AuditPort as AuditWriter

__all__ = ["AuditEvent", "AuditWriter"]
