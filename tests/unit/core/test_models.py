from __future__ import annotations

import pytest
from pydantic import ValidationError

from usep.core.models import SourceRecord


def test_source_record_exposes_the_surface_gate_py_depends_on() -> None:
    record = SourceRecord(
        source_system="jira",
        entity_type="issue",
        attributes={"kind": "story", "issue.summary": "Example"},
    )
    assert record.source_system == "jira"
    assert record.entity_type == "issue"
    assert record.attributes["kind"] == "story"


def test_source_record_defaults_entity_type_and_attributes() -> None:
    record = SourceRecord(source_system="confluence")
    assert record.entity_type is None
    assert record.attributes == {}


def test_source_record_is_frozen() -> None:
    record = SourceRecord(source_system="confluence")
    with pytest.raises(ValidationError):
        record.source_system = "jira"  # type: ignore[misc]
