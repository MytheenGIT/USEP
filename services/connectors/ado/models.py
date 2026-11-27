"""Azure DevOps work items, pull requests, repositories and their raw payloads."""

from __future__ import annotations

from common.source_document import SourceDocument


class AdoWorkItem(SourceDocument):
    """A work item (issue, task, bug, feature request)."""
    pass


class AdoPullRequest(SourceDocument):
    """A pull request."""
    pass


class AdoRepository(SourceDocument):
    """A repository."""
    pass
