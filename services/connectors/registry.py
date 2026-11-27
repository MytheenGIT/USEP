"""The set of sources and how to build each. This is the one place that names them.

Adding a source: create `<source>/{client,models,connector,factory}.py`, add a settings block to `config.py`, add its name
to SOURCES, and add a parser on the pipeline side. The container, scheduler, API routes and Lambda handler read this
registry, so none of them changes. Factories are imported on demand: a Lambda running one source loads only that source.
"""
from __future__ import annotations

import importlib
from typing import Any

from config import Settings

SOURCES: tuple[str, ...] = ("jira", "gitlab", "confluence", "figma", "github", "servicenow", "ado")


def build_source(name: str, settings: Settings, binary_store: Any | None = None) -> tuple[Any, Any]:
    """Return (client, connector) for one source. The client is returned so the caller can close it.

    `binary_store` receives downloaded attachments and exports. It is None in Lambda, which has no durable disk:
    sources then keep binary metadata only. Sources that download nothing ignore it."""
    if name not in SOURCES:
        raise ValueError(f"unknown source '{name}'")
    return importlib.import_module(f"{name}.factory").build(settings, binary_store)


def interval_minutes(name: str, settings: Settings) -> int:
    """Schedule interval for a source: SchedulerSettings.<name>_interval_minutes, else hourly."""
    return getattr(settings.scheduler, f"{name}_interval_minutes", 60)
