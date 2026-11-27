from pathlib import Path

import pytest

import sources_file as sf
from config import Settings

SHIPPED = Path(__file__).resolve().parents[3] / "config" / "sources.yaml"


def write(tmp_path, text):
    p = tmp_path / "s.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_shipped_file_loads_and_changes_nothing_but_servicenow_and_figma_state():
    doc = sf.load(SHIPPED)
    assert not sf.enabled(doc, "figma") and sf.enabled(doc, "jira")
    s = sf.apply(Settings(), doc)
    assert s.jira.jql_queries == [] and s.scheduler.jira_interval_minutes == 30 and s.servicenow.tables == ["incident", "change_request"]


def test_values_are_applied_and_an_env_variable_wins(tmp_path, monkeypatch):
    f = write(tmp_path, "defaults: {backfill_since: '2026-05-27T00:00:00Z'}\nsources:\n  gitlab:\n    interval_minutes: 10\n    scopes: [grp/app]\n  github:\n    scopes: [org/repo]\n")
    monkeypatch.setenv("USEP_INGESTION_GITHUB_REPOS", '["env/wins"]')
    s = sf.apply(Settings(), sf.load(f))
    assert s.backfill_since.startswith("2026-05-27") and s.gitlab.project_ids == ["grp/app"] and s.scheduler.gitlab_interval_minutes == 10
    assert s.github.repos == ["env/wins"]


@pytest.mark.parametrize("body,msg", [
    ("sources:\n  jira:\n    api_token: abc\n", "credential"),
    ("sources:\n  jira:\n    password: x\n", "credential"),
    ("sources:\n  nosuch: {}\n", "unknown source"),
    ("sources:\n  jira:\n    interval_minutes: 0\n", "positive integer"),
    ("sources:\n  jira:\n    scopes: [1]\n", "non-empty strings"),
    ("sources:\n  jira:\n    acl_mappings: {'project:A': [nogroup]}\n", "principals"),
    ("surprise: 1\n", "top level"),
])
def test_bad_file_fails_closed(tmp_path, body, msg):
    with pytest.raises(sf.SourcesFileError, match=msg):
        sf.load(write(tmp_path, body))
