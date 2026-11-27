from __future__ import annotations

from common.source_document import SourceDocument


class ServiceNowDocument(SourceDocument):
    """One ServiceNow record (an incident, change request, problem, ...). Reference fields keep their display name."""

    table: str
    number: str
    sys_id: str
    short_description: str = ""
    description: str | None = None
    state: str | None = None
    priority: str | None = None
    category: str | None = None
    assignment_group: str | None = None
    assigned_to: str | None = None
    configuration_item: str | None = None
    opened_at: str | None = None
    closed_at: str | None = None
