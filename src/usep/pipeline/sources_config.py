"""ACL mappings from `config/sources.yaml` (diagram A, 'Source onboarding: ... ACL mappings').

A data owner may state who governs a scope (`project:ABC` -> `group:abc-team`). The mapping can only restrict: the record
stays owners-only, and the principals travel with it so query-time filtering can use them. A mapping can never open a scope:
stating one open needs the source's own ACL. Anything not mapped stays as the connector harvested it (unknown means owners only).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from usep.pipeline.normalize.record import Acl


class SourcesConfigError(Exception):
    pass


def load_acl_mappings(path: str | Path) -> dict[str, tuple[str, ...]]:
    """`{"<source>:<scope kind>:<value>": (principals,)}`, for example `jira:project:ABC`."""
    p = Path(path)
    if not p.is_file():
        return {}
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: dict[str, tuple[str, ...]] = {}
    for source, body in (doc.get("sources") or {}).items():
        for scope, who in ((body or {}).get("acl_mappings") or {}).items():
            if not isinstance(who, list) or not who or not all(isinstance(x, str) and ":" in x for x in who):
                raise SourcesConfigError(f"{source}.{scope}: needs principals like group:name")
            out[f"{source}:{scope}"] = tuple(who)
    return out


def apply_mappings(source: str, acl: Acl, mappings: Mapping[str, tuple[str, ...]]) -> Acl:
    """Add the mapped principals for every scope on this ACL. Restrictive only; returns `acl` unchanged if nothing matches."""
    principals: list[str] = []
    for scope in acl.scopes:
        principals += mappings.get(f"{source}:{scope}", ())
    if not principals:
        return acl
    return Acl(True, acl.scheme or "owner_mapping", tuple(dict.fromkeys((*acl.principals, *principals))), True, acl.scopes)
