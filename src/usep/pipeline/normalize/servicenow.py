"""ServiceNow incident or change request (Table API row) to a canonical record."""
from __future__ import annotations

from typing import Any, Mapping

from usep.pipeline.normalize.record import UNKNOWN_ACL, Record


_SN_PREFIX = {"INC": "incident", "CHG": "change_request"}


def _sv(v: Any) -> Any:
    return v.get("value") if isinstance(v, Mapping) else v


def parse(raw: Mapping[str, Any], ref: str = "") -> list[Record]:
    number = str(_sv(raw.get("number")) or "")
    table = _SN_PREFIX.get(number[:3]) or str(_sv(raw.get("sys_class_name")) or "")
    if table not in _SN_PREFIX.values():
        raise ValueError(f"unsupported ServiceNow table {table!r}")
    upd = str(_sv(raw.get("sys_updated_on")) or "")
    iso = upd.replace(" ", "T") + "Z" if upd and "T" not in upd else upd          # the instance stores UTC
    short, desc = str(_sv(raw.get("short_description")) or ""), str(_sv(raw.get("description")) or "")
    scope = {"number": number, "short_description": short, "state": _sv(raw.get("state")),
             "priority": _sv(raw.get("priority")), "sys_id": _sv(raw.get("sys_id"))}
    return [Record("servicenow", table, number, upd, iso, short or number,
                   "\n\n".join(p for p in [short, desc] if p), UNKNOWN_ACL, [],
                   {k: v for k, v in scope.items() if v not in (None, "")})]
