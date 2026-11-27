"""Label resolution: effective properties and explainable precedence.

Precedence is Project > Application > Organisation > Domain/Industry > Core. Rules enforced:
- the core attribute set and each core attribute's type never change;
- a lower layer may add properties, set defaults, make a property required, or narrow allowed values;
- it may not make a required property optional, widen allowed values, or change an inherited type;
- the winning value and every contribution stay visible (`EffectiveProperty.contributions`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from usep.labelling.resolver_types import PropertyDef
from usep.ontology.view import LEVELS, OntologyView


@dataclass(slots=True)
class EffectiveProperty:
    name: str
    type: str
    required: bool
    default: Any
    allowed_values: tuple[str, ...] | None
    pattern: str | None
    origin: str                        # inherited | overridden | custom
    value_layer: str                   # level that supplied the winning default / rule
    contributions: list[dict[str, Any]] = field(default_factory=list)


def _inherited(view: OntologyView, concept: str) -> dict[str, PropertyDef]:
    out: dict[str, PropertyDef] = {}
    for name, a in view.bundle.concepts[concept].attributes.items():
        allowed = tuple(sorted(view.vocabulary(a.values_ref))) if a.values_ref and view.vocabulary(a.values_ref) else None
        t = "enum" if a.values_ref else a.type
        out[name] = PropertyDef(name, t, a.required, None, allowed, None, None, "many" if a.multi else "one")
    return out


def weakening_problems(d: Any, view: OntologyView, others: Sequence[Any] = ()) -> list[str]:
    """Problems if `d` (a LabelDefinition) would weaken what its parent concept already requires."""
    base = _inherited(view, d.parent_concept)
    errs = []
    for p in d.properties:
        b = base.get(p.name)
        if b is None:
            continue
        if b.type != p.type and not (b.type == "enum" and p.type == "string"):
            errs.append(f"property {p.name}: cannot change inherited type {b.type} to {p.type}")
        if b.required and not p.required:
            errs.append(f"property {p.name}: cannot make a required property optional")
        if b.allowed_values is not None:
            if p.allowed_values is not None and not set(p.allowed_values) <= set(b.allowed_values):
                extra = sorted(set(p.allowed_values) - set(b.allowed_values))
                errs.append(f"property {p.name}: allowed values may only narrow the inherited set (not allowed: {', '.join(extra)})")
        allowed = p.allowed_values if p.allowed_values is not None else b.allowed_values
        if p.default is not None and allowed is not None and str(p.default) not in allowed:
            errs.append(f"property {p.name}: default {p.default!r} is not an allowed value")
    return errs


def effective_properties(view: OntologyView, concept: str, definitions: Iterable[Any]) -> dict[str, EffectiveProperty]:
    """The concept's properties after applying every ACTIVE definition whose parent is the concept or an ancestor,
    least specific level first, so the most specific level wins. Invalid (weakening) properties are skipped."""
    eff: dict[str, EffectiveProperty] = {}
    for name, p in _inherited(view, concept).items():
        eff[name] = EffectiveProperty(name, p.type, p.required, None, p.allowed_values, None, "inherited", "core",
                                      [{"layer": "core", "source": "core", "required": p.required}])
    ancestors = set(view.ancestors(concept))
    active = [d for d in definitions if d.active and d.parent_concept in ancestors]
    for d in sorted(active, key=lambda x: (LEVELS.index(x.level), x.id)):
        bad = {e.split(":")[0] for e in weakening_problems(d, view)}
        for p in d.properties:
            if f"property {p.name}" in bad:
                continue
            cur = eff.get(p.name)
            note = {"layer": d.level, "source": d.id, "default": p.default, "required": p.required}
            if cur is None:
                eff[p.name] = EffectiveProperty(p.name, p.type, p.required, p.default, p.allowed_values, p.pattern,
                                                "custom", d.level, [note])
                continue
            cur.contributions.append(note)
            if p.default is not None:
                cur.default, cur.value_layer = p.default, d.level
            cur.required = cur.required or p.required
            if p.allowed_values is not None:
                cur.allowed_values = p.allowed_values
            if p.pattern:
                cur.pattern = p.pattern
            if cur.origin == "inherited":
                cur.origin = "overridden"
    return eff
