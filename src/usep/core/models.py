from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """The part of a source record the ontology gate reads. The pipeline repo's fuller model may replace it."""

    source_system: str
    entity_type: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    source_id: str = ""
