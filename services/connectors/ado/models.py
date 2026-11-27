from __future__ import annotations

from common.source_document import SourceDocument


class AdoDocument(SourceDocument):
    """An Azure DevOps work item ('work_item') or pull request ('pull_request')."""

    project: str
    work_item_type: str | None = None
    state: str | None = None                     # work item: the process state. PR: opened | merged | closed
    labels: list[str] = []
    repository: str | None = None                # PRs
    relation_count: int = 0                      # work item relations are kept in raw_payload
