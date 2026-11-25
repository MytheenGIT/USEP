"""Base provenance-carrying document returned by every connector.

Every connector normalizes its source payload into a subclass of
``SourceDocument``. Subclasses add source-specific fields but must never
collapse structured source data (comments, changelog, diffs, labels, ...)
into the flat ``content`` string -- that stays usable for naive downstream
consumers, while the structured fields stay available for the chunker.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceType(StrEnum):
    JIRA = "jira"
    GITLAB = "gitlab"
    CONFLUENCE = "confluence"
    FIGMA = "figma"


class SourceDocument(BaseModel):
    """Common provenance + normalization contract for all ingested objects."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    # --- provenance (required for every object, see Provenance Requirements) ---
    source: SourceType
    source_type: str = Field(
        description="Object kind within the source, e.g. 'issue', 'merge_request', 'page', 'frame'."
    )
    source_object_id: str = Field(description="Stable id of the object in its source system.")
    source_url: str = Field(description="Deep link back to the object in the source system.")
    retrieved_at: datetime = Field(description="UTC timestamp when this connector fetched the object.")
    raw_payload: dict[str, Any] = Field(
        description="Untouched source API payload, preserved for traceability and re-normalization."
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
