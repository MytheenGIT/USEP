from __future__ import annotations

import pytest

from console_api.targets import (
    TargetError,
    confluence_space_key,
    figma_file_key,
    gitlab_project,
    jira_project_key,
)


def test_jira_accepts_key_or_project_link() -> None:
    assert jira_project_key("pay") == "PAY"
    assert jira_project_key("https://acme.atlassian.net/jira/software/projects/OPS/boards/1") == "OPS"


@pytest.mark.parametrize("entry", ["", "1ABC", "PAY OR 1=1", "A", "https://acme.atlassian.net/jira/software", "ftp://x/projects/PAY"])
def test_jira_rejects_unsafe_or_missing_key(entry: str) -> None:
    with pytest.raises(TargetError):
        jira_project_key(entry)


def test_confluence_space() -> None:
    assert confluence_space_key("PAY") == "PAY"
    assert confluence_space_key("https://acme.atlassian.net/wiki/spaces/~team/overview") == "~team"
    with pytest.raises(TargetError):
        confluence_space_key("a/b")


def test_gitlab_project_path_id_and_link() -> None:
    assert gitlab_project("group/sub/proj") == "group/sub/proj"
    assert gitlab_project("42") == "42"
    assert gitlab_project("https://gitlab.example.com/group/proj.git") == "group/proj"
    assert gitlab_project("https://gitlab.example.com/group/proj/-/merge_requests") == "group/proj"
    with pytest.raises(TargetError):
        gitlab_project("onlygroup")
    with pytest.raises(TargetError):
        gitlab_project("a/../b?x")


def test_figma_key_or_link() -> None:
    assert figma_file_key("AbCdEf1234567890") == "AbCdEf1234567890"
    assert figma_file_key("https://www.figma.com/design/AbCdEf1234567890/My-file?node-id=1") == "AbCdEf1234567890"
    with pytest.raises(TargetError):
        figma_file_key("https://example.com/design/AbCdEf1234567890/x")
    with pytest.raises(TargetError):
        figma_file_key("short")
