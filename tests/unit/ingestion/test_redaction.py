from __future__ import annotations

from usep.ingestion.runtime.redaction import redact_headers, redact_text


def test_redact_headers_covers_every_listed_name_case_insensitively() -> None:
    headers = {
        "Authorization": "Bearer abc123",
        "PRIVATE-TOKEN": "glpat-xyz",  # SYNTHETIC
        "Cookie": "session=abc",
        "Set-Cookie": "session=abc; Path=/",
        "JOB-TOKEN": "xyz",
        "X-API-KEY": "xyz",
        "Proxy-Authorization": "Basic abc",
        "Accept": "application/json",
    }
    redacted = redact_headers(headers)
    for name in (
        "Authorization",
        "PRIVATE-TOKEN",
        "Cookie",
        "Set-Cookie",
        "JOB-TOKEN",
        "X-API-KEY",
        "Proxy-Authorization",
    ):
        assert redacted[name] == "<redacted>"
    assert redacted["Accept"] == "application/json"


def test_redact_headers_does_not_mutate_input() -> None:
    original = {"Authorization": "Bearer abc123"}
    redact_headers(original)
    assert original["Authorization"] == "Bearer abc123"


def test_redact_text_hides_bearer_token() -> None:
    text = "call failed: Bearer abcdefgh12345678 was rejected"
    redacted = redact_text(text)
    assert "abcdefgh12345678" not in redacted
    assert "Bearer <redacted>" in redacted
