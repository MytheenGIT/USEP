"""Parse and normalize a raw snapshot into canonical records (C-02 'Parse / extract' and 'Normalize').

One module per source in this package; each exposes `parse(raw, ref) -> list[Record]`. To add a source: add a module,
register it in PARSERS below, and add its raw family to `usep.pipeline.topics`.

A canonical record is what the ontology mappings read (`ontology/packs/app/*/mappings/*.yml`). One snapshot can yield
several records: a Jira issue yields the issue and one `issue_link` per link. Sources whose objects the packs name
generically report that name: GitLab, GitHub and ADO pull requests are system `git`, object `pull_request`.
Nothing here guesses a value. A field the source does not carry stays absent and the gate decides.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from usep.pipeline.normalize import ado, confluence, figma, github, gitlab, jira, servicenow
from usep.pipeline.normalize.record import UNKNOWN_ACL, Acl, Record, adf_to_text, html_to_text

PARSERS: dict[str, Callable[[Mapping[str, Any], str], list[Record]]] = {
    "jira": jira.parse, "gitlab": gitlab.parse, "confluence": confluence.parse, "figma": figma.parse,
    "github": github.parse, "servicenow": servicenow.parse, "ado": ado.parse,
}


def normalize(source: str, source_ref: str, raw: Mapping[str, Any]) -> list[Record]:
    """Raw snapshot to canonical records. Raises KeyError/ValueError when the payload is not the expected shape;
    the worker turns that into a quarantine entry (schema drift) instead of dropping the record."""
    parser = PARSERS.get(source)
    if parser is None:
        raise ValueError(f"no parser for source '{source}'")
    return parser(raw, source_ref)


__all__ = ["PARSERS", "UNKNOWN_ACL", "Acl", "Record", "adf_to_text", "html_to_text", "normalize"]
