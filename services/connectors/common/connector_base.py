"""Common connector contract. Each source connector is independent and
pluggable: adding a new source means adding one client + one connector
that implements this Protocol, with no changes to SyncService or the API.
"""

from __future__ import annotations

from typing import Protocol

from common.source_document import SourceDocument


class SourceConnector(Protocol):
    source: str

    async def fetch(self, cursor: str | None) -> tuple[list[SourceDocument], str | None]:
        """Fetch new/updated objects since ``cursor``.

        Returns the normalized documents and the new cursor value to persist
        (via the CursorManager interface) on success. Returning None for the
        cursor means "no forward progress to record" (e.g. nothing fetched).
        """
        ...
