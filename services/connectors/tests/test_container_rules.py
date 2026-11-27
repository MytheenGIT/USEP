from __future__ import annotations

import base64
import os
import uuid

import pytest

from config import Settings
from container import Container
from usep.core.errors import ConfigError

KEK = base64.b64encode(os.urandom(32)).decode()


def _settings(tmp_path, **sources) -> Settings:
    return Settings(tenant_id=uuid.uuid4(), dev_kek_b64=KEK, output_dir=str(tmp_path), **sources)


def test_service_will_not_start_without_tenant_bucket_and_key() -> None:
    with pytest.raises(ConfigError) as caught:
        Container(Settings(raw_store="s3"))
    message = str(caught.value)
    assert "USEP_INGESTION_TENANT_ID" in message and "USEP_INGESTION_S3_BUCKET" in message and "DEV_KEK" in message


def test_the_file_store_needs_no_bucket_and_s3_is_a_switch_away(tmp_path) -> None:
    from raw_store import make_object_store
    from usep.adapters.local_files.object_store import FileObjectStore
    from usep.adapters.s3.object_store import S3ObjectStore

    assert isinstance(make_object_store(Settings(output_dir=str(tmp_path))), FileObjectStore)
    assert isinstance(make_object_store(Settings(raw_store="s3", s3_bucket="b")), S3ObjectStore)


def test_no_source_is_mandatory(tmp_path) -> None:
    container = Container(_settings(tmp_path))

    assert container.sync_service.available_sources == []
    assert [(r["source"], r["enabled"], r["running"]) for r in container.source_overview()] == [
        ("ado", False, False), ("jira", False, False), ("confluence", False, False), ("gitlab", False, False),
        ("github", False, False), ("servicenow", False, False), ("figma", False, False),
    ]


def test_only_the_selected_sources_run(tmp_path) -> None:
    container = Container(
        _settings(
            tmp_path,
            confluence={"enabled": True, "base_url": "https://x.atlassian.net", "email": "a@b.c", "api_token": "t", "space_keys": "ENG, OPS"},
            gitlab={"enabled": True, "private_token": "t", "all_member_projects": True},
        )
    )

    assert sorted(container.sync_service.available_sources) == ["confluence", "gitlab"]
    assert container.sync_service.scopes("confluence") == ["ENG", "OPS"]
    assert container.sync_service.has_dynamic_scopes  # GitLab finds its repositories on its own


def test_a_selected_source_must_be_complete_and_all_gaps_are_reported_together(tmp_path) -> None:
    with pytest.raises(ConfigError) as caught:
        Container(_settings(tmp_path, jira={"enabled": True, "base_url": "https://x.atlassian.net"}, figma={"enabled": True}))

    message = str(caught.value)
    assert "jira is selected but incomplete" in message and "USEP_INGESTION_JIRA_EMAIL is required" in message
    assert "USEP_INGESTION_JIRA_API_TOKEN is required" in message and "JQL" in message and "PROJECT_KEYS" in message
    assert "figma is selected but incomplete" in message and "USEP_INGESTION_FIGMA_FILE_KEYS is required" in message


def test_values_for_a_source_that_is_not_selected_are_ignored_not_checked(tmp_path) -> None:
    settings = _settings(tmp_path, jira={"email": "a@b.c", "project_keys": "not a key!"})

    assert settings.jira.problems() == [] and settings.jira.filled_but_not_selected()
    assert Container(settings).sync_service.available_sources == []


def test_figma_waits_for_the_dpia_even_when_selected(tmp_path) -> None:
    figma = {"enabled": True, "access_token": "t", "file_keys": "KEY"}

    blocked = Container(_settings(tmp_path, figma=figma))
    assert blocked.sync_service.available_sources == []
    assert "DPIA" in [r for r in blocked.source_overview() if r["source"] == "figma"][0]["blocked_reason"]

    assert Container(_settings(tmp_path, figma={**figma, "dpia_approved": True})).sync_service.available_sources == ["figma"]


def test_github_and_servicenow_run_when_selected(tmp_path) -> None:
    container = Container(
        _settings(
            tmp_path,
            github={"enabled": True, "token": "t", "repositories": "acme/checkout, git@github.com:acme/billing.git"},
            servicenow={"enabled": True, "base_url": "https://dev1.service-now.com", "username": "u", "password": "p", "tables": "incident,change_request"},
        )
    )

    assert sorted(container.sync_service.available_sources) == ["github", "servicenow"]
    assert container.sync_service.scopes("github") == ["acme/checkout", "acme/billing"]
    assert container.sync_service.scopes("servicenow") == ["incident", "change_request"]
