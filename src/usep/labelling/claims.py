"""Competing claims about one attribute: keep all, pick a winner by the organisation pack's rule.

Winner order (HLD 5.3, LLD 5.3): 1. the attribute's source precedence order, 2. higher source_version,
3. source_system_priority then lexical source_id. An attribute with no precedence rule has NO winner and the
conflict stays open (recency never decides). Claims are never overwritten or dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class Claim:
    attribute: str
    value: Any
    source_system: str
    source_id: str = ""
    source_version: str = ""


@dataclass(slots=True)
class Resolution:
    attribute: str
    winner: Claim | None
    conflict: bool
    reason: str
    claims: list[Claim] = field(default_factory=list)


def resolve_claims(attribute: str, claims: Sequence[Claim], precedence: Mapping[str, Sequence[str]],
                   system_priority: Sequence[str] = ()) -> Resolution:
    claims = list(claims)
    if len({repr(c.value) for c in claims}) <= 1:
        return Resolution(attribute, claims[0] if claims else None, False, "all claims agree" if claims else "no claims", claims)
    order = list(precedence.get(attribute, ()))
    if not order:
        return Resolution(attribute, None, True, f"no precedence rule for {attribute}: conflict stays open", claims)
    ranked = [c for c in claims if c.source_system in order]
    if not ranked:
        return Resolution(attribute, None, True, f"no claim comes from a source ranked for {attribute}: conflict stays open", claims)
    best = min(order.index(c.source_system) for c in ranked)
    top = [c for c in ranked if order.index(c.source_system) == best]
    reason = f"source precedence for {attribute}: {' > '.join(order)}"
    if len({repr(c.value) for c in top}) > 1:
        top.sort(key=lambda c: c.source_version, reverse=True)
        top = [c for c in top if c.source_version == top[0].source_version]
        reason = "same source, higher source_version"
        if len({repr(c.value) for c in top}) > 1:
            top.sort(key=lambda c: (system_priority.index(c.source_system) if c.source_system in system_priority else 99, c.source_id))
            reason = "tie-break: source_system_priority then lexical source_id"
    return Resolution(attribute, top[0], True, reason, claims)
