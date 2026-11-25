from __future__ import annotations

from datetime import UTC, datetime

from confluence.models import ConfluenceDocument, ConfluenceVersion
from figma.models import FigmaDocument
from gitlab.models import GitLabDocument
from jira.models import JiraComment, JiraDocument
from common.source_document import SourceType


def test_jira_document_keeps_comments_and_changelog_separate_from_content() -> None:
    doc = JiraDocument(
        source=SourceType.JIRA,
        source_type="issue",
        source_object_id="ABC-1",
        source_url="https://example.atlassian.net/browse/ABC-1",
        retrieved_at=datetime.now(UTC),
        raw_payload={"key": "ABC-1"},
        title="Example",
        content="Issue description",
        metadata={},
        issue_key="ABC-1",
        summary="Example",
        description="Issue description",
        status="To Do",
        comments=[JiraComment(comment_id="1", body="hello", raw={})],
    )

    assert doc.content == "Issue description"
    assert doc.comments[0].body == "hello"
    assert doc.raw_payload == {"key": "ABC-1"}


def test_gitlab_document_requires_structured_fields() -> None:
    doc = GitLabDocument(
        source=SourceType.GITLAB,
        source_type="merge_request",
        source_object_id="1!2",
        source_url="https://gitlab.com/group/proj/-/merge_requests/2",
        retrieved_at=datetime.now(UTC),
        raw_payload={},
        title="Fix bug",
        content="",
        metadata={},
        project_id="1",
        mr_iid="2",
        state="opened",
    )
    assert doc.commits == []
    assert doc.diffs == []


def test_confluence_document_preserves_hierarchy() -> None:
    doc = ConfluenceDocument(
        source=SourceType.CONFLUENCE,
        source_type="page",
        source_object_id="100",
        source_url="https://example.atlassian.net/wiki/x",
        retrieved_at=datetime.now(UTC),
        raw_payload={},
        title="Page",
        content="<p>body</p>",
        metadata={},
        space_key="ENG",
        page_id="100",
        version=ConfluenceVersion(number=1),
    )
    assert doc.children == []
    assert doc.version.number == 1


def test_figma_document_flattens_pages_without_merging_text() -> None:
    doc = FigmaDocument(
        source=SourceType.FIGMA,
        source_type="file",
        source_object_id="file123",
        source_url="https://www.figma.com/file/file123",
        retrieved_at=datetime.now(UTC),
        raw_payload={},
        title="Design File",
        content="",
        metadata={},
        file_key="file123",
        file_name="Design File",
    )
    assert doc.pages == []
    assert doc.frames == []
    assert doc.text_layers == []
