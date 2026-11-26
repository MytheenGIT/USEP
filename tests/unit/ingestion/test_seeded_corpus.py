from __future__ import annotations

from tests.fixtures.sensitive_corpus import SEEDED_SECRET_CORPUS

from usep.ingestion.sensitive.detector import detect


def test_seeded_secret_corpus_blocked_before_write() -> None:
    """CC-05: every seeded secret/PII shape is detected, and never appears in the
    detector's own result (counts only, never matched text)."""
    for text, expected_reason in SEEDED_SECRET_CORPUS:
        result = detect(text)
        assert result.matched is True, f"expected a match for: {text!r}"
        assert result.counts.get(expected_reason, 0) >= 1, f"expected {expected_reason} for: {text!r}"
        assert text not in repr(result.counts)
