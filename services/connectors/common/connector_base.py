"""Common connector contract.

Each connector exposes the scopes it is configured for (a JQL query, a
GitLab repository, a Confluence space, a Figma file) and fetches one scope
at a time. Failures of a single object are reported in ``ScopeFetch.errors``
instead of raising, so one bad page or MR never fails the whole run
(spec Module 2). An exception from ``fetch_scope`` means the scope itself
could not be read (auth, listing call failed) and fails only that scope.

Cursors are not computed by connectors: SyncService derives them from the
documents' ``source_version`` and the errors' ``source_version`` (see
``next_cursor``), so the rule is the same for every source.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from common.source_document import SourceDocument, SourceType


class ObjectError(BaseModel):
    scope: str
    object_id: str | None = None
    source_version: str | None = None
    error: str

    def __str__(self) -> str:
        target = f"{self.scope}/{self.object_id}" if self.object_id else self.scope
        return f"{target}: {self.error}"


class ScopeFetch(BaseModel):
    documents: list[SourceDocument] = []
    errors: list[ObjectError] = []


class ScopeCheck(BaseModel):
    scope: str
    ok: bool
    detail: str = ""


class SourceCheck(BaseModel):
    """Result of asking a source whether the saved credentials and scopes really work (read-only calls)."""

    ok: bool
    detail: str = ""
    scopes: list[ScopeCheck] = []


class SourceConnector(Protocol):
    source: SourceType

    @property
    def scopes(self) -> list[str]:
        """Configured scopes, in the form the connector was given them."""
        ...

    async def fetch_scope(self, scope: str, cursor: str | None) -> ScopeFetch:
        """Fetch objects in ``scope`` updated at or after ``cursor`` (a UTC ISO timestamp)."""
        ...

    # Optional, found with getattr by the service:
    #   async def check(self) -> SourceCheck       credentials and every scope, with read-only calls
    #   async def refresh_scopes(self) -> None     re-discover scopes (GitLab, when it fetches all member repos)


def next_cursor(previous: str | None, fetched: ScopeFetch) -> str | None:
    """Cursor to persist after a scope fetch.

    - No errors: the newest ``source_version`` fetched (or the previous cursor).
    - Errors that carry a ``source_version``: the oldest failed version, so the
      next run (which fetches ``>= cursor``) picks the failed objects up again.
    - Errors without a version: keep the previous cursor; we cannot tell what was missed.
    """
    if fetched.errors:
        failed = [e.source_version for e in fetched.errors]
        if any(v is None for v in failed):
            return previous
        oldest_failed = min(v for v in failed if v is not None)
        return max(previous, oldest_failed) if previous else oldest_failed
    versions = [d.source_version for d in fetched.documents if d.source_version]
    if not versions:
        return previous
    newest = max(versions)
    return max(previous, newest) if previous else newest
