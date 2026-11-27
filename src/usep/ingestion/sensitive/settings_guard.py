"""Scans every string field of `Settings` for a credential-shaped value before it
is trusted (section 5.1). Lives here, not in `usep.core.config`, because
`usep.core` has no dependency on any other usep package (`usep/core/__init__.py`);
this module legitimately depends on both `usep.core.config` and
`usep.ingestion.sensitive.patterns`, so the scan lives on this side of that line.

Use `load_settings()` wherever `Settings` is built from real configuration; the
plain `Settings(...)` constructor (used directly by `usep.core`'s own unit tests)
skips this extra scan.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from usep.core.config import Settings
from usep.core.errors import ConfigError
from usep.ingestion.sensitive import patterns as p


def find_leaked_secret_pattern(value: str) -> str | None:
    """The name of the first credential-shaped pattern matching `value`, or `None`."""
    for name, pattern in p.SECRET_PATTERNS.items():
        if pattern.search(value):
            return name
    return None


def assert_no_leaked_secrets(data: Mapping[str, Any], *, path: str = "") -> None:
    """Recursively scans a (nested) mapping of settings values. Raises `ConfigError`
    naming the field path and pattern name only — never the matched value."""
    for key, value in data.items():
        field_path = f"{path}.{key}" if path else str(key)
        if isinstance(value, str):
            pattern_name = find_leaked_secret_pattern(value)
            if pattern_name is not None:
                raise ConfigError(f"{field_path}: value matches credential pattern {pattern_name!r}")
        elif isinstance(value, Mapping):
            assert_no_leaked_secrets(value, path=field_path)


def load_settings(**overrides: Any) -> Settings:
    """Construct `Settings`, then scan every string field for a credential-shaped
    value. Raises `ConfigError` naming the field and pattern or error type only, never
    the value.
    """
    try:
        settings = Settings(**overrides)
    except ValidationError as err:
        problems = ", ".join(f"{'.'.join(str(part) for part in e['loc'])}: {e['type']}" for e in err.errors())
        # `from None`: pydantic's error text echoes the offending input, which may be a credential.
        raise ConfigError(f"invalid settings ({problems})") from None
    assert_no_leaked_secrets(settings.model_dump(mode="python"))
    return settings
