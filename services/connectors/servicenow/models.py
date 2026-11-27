from __future__ import annotations

from common.source_document import SourceDocument


class ServiceNowDocument(SourceDocument):
    """An incident or change request. State and priority are the instance's codes, translated by the project pack."""

    table: str                                   # incident | change_request
    number: str
    sys_id: str
    state: str | None = None
    priority: str | None = None
    assignment_group: str | None = None          # sys_id; resolved to a Team by the resolver
    cmdb_ci: str | None = None                   # sys_id of the configuration item
    caused_by: str | None = None                 # sys_id of the change (incidents only)
