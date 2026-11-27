"""Saved results: what each source returned, kept per configuration so its graph can be rebuilt later.

A configuration that gets another connector added does not read the earlier ones again (their tokens are not kept). Its graph
is rebuilt from what they returned the first time. The documents are saved as readable JSON next to the configuration,
like the run files, and are loaded back into their typed models.
"""

from __future__ import annotations

import structlog

from common.source_document import SourceDocument
from confluence.models import ConfluenceDocument
from figma.models import FigmaDocument
from github.models import GitHubDocument
from gitlab.models import GitLabDocument
from gitrepo.models import GitCommitDocument
from jira.models import JiraDocument
from servicenow.models import ServiceNowDocument

logger = structlog.get_logger(__name__)


def model_for(source: str, source_type: str) -> type[SourceDocument]:
    if source_type == "commit":  # read over SSH, for GitHub or GitLab
        return GitCommitDocument
    return {
        "jira": JiraDocument, "confluence": ConfluenceDocument, "gitlab": GitLabDocument, "github": GitHubDocument,
        "servicenow": ServiceNowDocument, "figma": FigmaDocument,
    }[source]


def dump_documents(documents: list[SourceDocument]) -> list[dict]:
    return [d.model_dump(mode="json") for d in documents]


def load_documents(source: str, items: list[dict]) -> list[SourceDocument] | None:
    """The documents, or None if any of them cannot be read back (then the saved copy is not trusted at all)."""
    try:
        return [model_for(source, str(item.get("source_type", ""))).model_validate(item) for item in items]
    except Exception as exc:  # noqa: BLE001 -- a saved copy from another version of the models
        logger.warning("saved_documents.unreadable", source=source, error=type(exc).__name__)
        return None
