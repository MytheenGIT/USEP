"""Base provenance-carrying document returned by every connector.

Every connector normalizes its source payload into a subclass of
``SourceDocument``. Subclasses add source-specific fields but must never
collapse structured source data (comments, changelog, diffs, labels, ...)
into the flat ``content`` string -- that stays usable for naive downstream
consumers, while the structured fields stay available for the chunker.

The provenance fields follow LLD Section 3.5: every record carries
source_version, content_hash, an ACL reference and its extraction time
(``retrieved_at``).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceType(StrEnum):
    JIRA = "jira"
    GITLAB = "gitlab"
    CONFLUENCE = "confluence"
    FIGMA = "figma"
    GITHUB = "github"
    SERVICENOW = "servicenow"
    ADO = "ado"


def hash_payload(payload: Any) -> str:
    """SHA-256 over canonical JSON (sorted keys, UTF-8, no insignificant whitespace)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SourceDocument(BaseModel):
    """Common provenance + normalization contract for all ingested objects."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    # --- provenance (required for every object, see Provenance Requirements) ---
    source: SourceType
    source_type: str = Field(
        description="Object kind within the source, e.g. 'issue', 'merge_request', 'page', 'file'."
    )
    source_object_id: str = Field(description="Stable id of the object in its source system.")
    source_url: str = Field(description="Deep link back to the object in the source system.")
    retrieved_at: datetime = Field(description="UTC timestamp when this connector fetched the object.")
    raw_payload: dict[str, Any] = Field(
        description="Untouched source API payload(s), preserved for traceability and re-normalization."
    )
    scope: str = Field(default="", description="Configured scope this object was fetched under (JQL, repo, space, file).")
    source_version: str | None = Field(
        default=None, description="Source's own last-updated time as UTC ISO 8601; also the cursor value."
    )
    content_hash: str = Field(default="", description="SHA-256 of the canonical raw payload; computed if empty.")
    acl: dict[str, Any] = Field(
        default_factory=dict, description="Source permission attributes harvested for later ACL mapping."
    )

    # --- light normalization, useful for downstream chunking ---
    title: str = Field(description="Short human-readable title of the object.")
    content: str = Field(
        default="",
        description=(
            "Best-effort flattened text for naive consumers. Structured fields on "
            "subclasses remain the source of truth and must not be merged away."
        ),
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Normalized, source-agnostic metadata.")

    @model_validator(mode="after")
    def _fill_content_hash(self) -> "SourceDocument":
        if not self.content_hash:
            self.content_hash = hash_payload(self.raw_payload)
        return self
