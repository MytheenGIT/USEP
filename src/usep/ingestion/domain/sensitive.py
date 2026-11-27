"""The sensitive-data detector's result type: counts and reason codes only.

Never the matched text itself (D3; organization rule: no SSN, Aadhaar, PAN or card number is ever
stored, processed for storage, or displayed; only a count may be kept).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """Result of a sensitive-data scan: match counts by reason, and whether any matched."""

    counts: dict[str, int]
    matched: bool
