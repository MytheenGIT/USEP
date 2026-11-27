from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_cryptography_is_a_base_dependency_because_the_writer_imports_it() -> None:
    dependencies = tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]

    assert any(dep.startswith("cryptography") for dep in dependencies)
