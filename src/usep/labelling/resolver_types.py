from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class PropertyDef:
    name: str
    type: str = "string"
    required: bool = False
    default: Any = None
    allowed_values: tuple[str, ...] | None = None
    pattern: str | None = None
    sensitivity: int | None = None
    cardinality: str = "one"          # one | many


def check_value(p: PropertyDef, value: Any) -> str:
    """'' if the value fits the property, else a short reason."""
    items = value if p.cardinality == "many" and isinstance(value, (list, tuple)) else [value]
    for v in items:
        if p.allowed_values is not None and str(v) not in p.allowed_values:
            return f"{v!r} is not an allowed value"
        t = p.type
        if t == "integer" and (isinstance(v, bool) or not isinstance(v, int)):
            return f"{v!r} is not an integer"
        if t == "decimal" and (isinstance(v, bool) or not isinstance(v, (int, float))):
            return f"{v!r} is not a number"
        if t == "boolean" and not isinstance(v, bool):
            return f"{v!r} is not a boolean"
        if t in ("string", "enum") and not isinstance(v, str):
            return f"{v!r} is not text"
        if t in ("date", "datetime"):
            try:
                datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            except ValueError:
                return f"{v!r} is not an ISO 8601 {t}"
        if p.pattern is not None and isinstance(v, str) and not re.fullmatch(p.pattern, v):
            return f"{v!r} does not match the required pattern"
    return ""
