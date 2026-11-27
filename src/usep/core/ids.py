"""UUID v7 generation (ground rule, section 1: every generated ID is UUID v7).

Uses the `uuid6` package rather than the stdlib (Python's `uuid` module gains
`uuid7()` only in 3.14+; this project targets 3.12, and the ground rules name
`uuid6` explicitly).
"""

from __future__ import annotations

import uuid

from uuid6 import uuid7


def new_id() -> uuid.UUID:
    """A fresh, time-ordered UUID v7. Use this for every generated ID in the system."""
    return uuid7()
