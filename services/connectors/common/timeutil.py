"""UTC timestamp helpers shared by connectors.

LLD Section 1: all timestamps are UTC ISO 8601 with millisecond precision.
Cursors and ``source_version`` values are always produced by ``to_utc_iso``
so that plain string comparison orders them correctly across sources.
"""

from __future__ import annotations

from datetime import UTC, datetime


def parse_ts(value: str | datetime | None) -> datetime | None:
    """Parse a source timestamp (ISO 8601, with or without a colon in the offset)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f%z")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_utc_iso(value: str | datetime | None) -> str | None:
    """Normalize any source timestamp to ``YYYY-MM-DDTHH:MM:SS.mmmZ``."""
    dt = parse_ts(value)
    if dt is None:
        return None
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
