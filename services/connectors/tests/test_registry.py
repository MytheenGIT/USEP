from __future__ import annotations

import pytest

import registry
from api.routes.sync import router
from config import Settings
from container import Container


def test_every_registered_source_builds_and_is_routed_and_scheduled():
    s = Settings()
    paths = {r.path for r in router.routes}
    for name in registry.SOURCES:
        client, connector = registry.build_source(name, s)
        assert connector.source.value == name
        assert isinstance(connector.scopes, list)
        assert f"/sync/{name}" in paths
        assert registry.interval_minutes(name, s) > 0
    assert "/sync/all" in paths


def test_container_wires_all_sources_and_unknown_is_rejected():
    assert sorted(Container(Settings()).sync_service.available_sources) == sorted(registry.SOURCES)
    with pytest.raises(ValueError):
        registry.build_source("nope", Settings())
