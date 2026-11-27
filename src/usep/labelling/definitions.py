"""Tenant custom-label definitions and their server-side validation.

A custom label is an alias, classification or extension of an EXISTING concept (`parent_concept`). It never
creates a concept. It may add optional properties, defaults, tighter allowed values, and required-ness.
It may never remove or loosen anything it inherits (additive only, ADR-08).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from usep.labelling.resolver_types import PropertyDef
from usep.ontology.view import LEVELS, OntologyView

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,62}$")
PROPERTY_TYPES = ("string", "integer", "decimal", "boolean", "date", "datetime", "enum")
STATUSES = ("draft", "active", "disabled")
TENANT_LEVELS = ("industry", "organization", "application", "project")   # the core is immutable from a tenant
MAX_PATTERN = 200
MAX_PROPERTIES = 50
MAX_ALIASES = 20


@dataclass(frozen=True, slots=True)
class LabelDefinition:
    id: str
    tenant_id: str
    level: str
    parent_concept: str
    display_name: str
    namespace: str = "custom"
    description: str = ""
    aliases: tuple[str, ...] = ()
    source_systems: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    when: Mapping[str, tuple[str, ...]] = field(default_factory=dict)      # same meaning as a pack mapping's `when`
    properties: tuple[PropertyDef, ...] = ()
    relationship_rules: tuple[str, ...] = ()                                # relationship ids this label may take part in
    version: int = 1
    status: str = "draft"
    created_by: str = ""
    created_at: str = ""
    updated_by: str = ""
    updated_at: str = ""

    @property
    def active(self) -> bool:
        return self.status == "active"

    def with_status(self, status: str) -> "LabelDefinition":
        return replace(self, status=status)


def validate_property(p: PropertyDef, view: OntologyView) -> list[str]:
    errs: list[str] = []
    if not ID_RE.match(p.name):
        errs.append(f"property {p.name!r}: name must be lower_snake_case")
    if p.type not in PROPERTY_TYPES:
        errs.append(f"property {p.name}: unknown type {p.type}")
    if p.pattern is not None:
        if len(p.pattern) > MAX_PATTERN:
            errs.append(f"property {p.name}: pattern longer than {MAX_PATTERN}")
        else:
            try:
                re.compile(p.pattern)
            except re.error as exc:
                errs.append(f"property {p.name}: invalid pattern ({exc})")
    if p.sensitivity is not None and p.sensitivity not in (0, 1, 2, 3):
        errs.append(f"property {p.name}: sensitivity must be 0 to 3")
    if p.default is not None:
        from usep.labelling.resolver_types import check_value
        bad = check_value(p, p.default)
        if bad:
            errs.append(f"property {p.name}: default {bad}")
    return errs


def validate_definition(d: LabelDefinition, view: OntologyView, existing: Sequence[LabelDefinition] = ()) -> list[str]:
    """Every reason the definition may not be saved. Empty means valid. `existing` are the tenant's other definitions."""
    from usep.labelling.resolver import weakening_problems
    errs: list[str] = []
    if not d.tenant_id:
        errs.append("tenant_id is required")
    if not ID_RE.match(d.id):
        errs.append("id must be lower_snake_case, 2 to 63 characters")
    if not NAMESPACE_RE.match(d.namespace):
        errs.append("namespace is not valid")
    if d.level == "core":
        errs.append("core definitions are immutable from a tenant")
    elif d.level not in LEVELS:
        errs.append(f"unknown ontology level {d.level}")
    if d.status not in STATUSES:
        errs.append(f"status must be one of {', '.join(STATUSES)}")
    if not d.display_name.strip():
        errs.append("display_name is required")
    if d.parent_concept not in view.bundle.concepts:
        errs.append(f"parent_concept {d.parent_concept} is not in the active ontology")
    if len(d.aliases) > MAX_ALIASES:
        errs.append(f"at most {MAX_ALIASES} aliases")
    if len(d.properties) > MAX_PROPERTIES:
        errs.append(f"at most {MAX_PROPERTIES} properties")
    names = [p.name for p in d.properties]
    if len(set(names)) != len(names):
        errs.append("duplicate property names")
    for p in d.properties:
        errs += validate_property(p, view)
        if p.name in view.common_attributes and p.name not in ("name", "summary"):
            errs.append(f"property {p.name}: reserved by the core common attributes")
    for r in d.relationship_rules:
        if r not in view.relationship_rules:
            errs.append(f"relationship rule {r} is not in the active ontology")
    for other in existing:
        if other.id == d.id or other.tenant_id != d.tenant_id or other.status == "disabled":
            continue
        if other.level == d.level and other.namespace == d.namespace and (
                other.display_name.lower() == d.display_name.lower()
                or {a.lower() for a in other.aliases} & ({d.display_name.lower()} | {a.lower() for a in d.aliases})):
            errs.append(f"term already defined at level {d.level} by {other.id} (CC-16)")
    if any(e.id == d.id and e.tenant_id != d.tenant_id for e in existing):
        errs.append("id belongs to another tenant")        # never reveals which one
    if d.parent_concept in view.bundle.concepts:
        errs += weakening_problems(d, view)
    return errs
