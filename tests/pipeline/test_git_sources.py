"""Pull requests and repositories from GitLab, GitHub and ADO (system `git`)."""


from tests.pipeline.helpers import (edges, gh_pr, published, raw_event)




def test_gitlab_mr_becomes_change(env):
    s3, _, w = env
    mr = {"iid": 7, "project_id": 5, "title": "Add bus", "state": "merged", "updated_at": "2026-03-01T00:00:00Z"}
    w.handle(raw_event(s3, "gitlab", "5!7", mr))
    p = published(s3, "entity.product")[0]["payload"]
    assert p["type"] == "Change" and p["attributes"]["change_state"] == "released" and p["attributes"]["source_id"] == "5!7"


def test_mr_citing_jira_key_gets_references_edge_with_provenance_and_pending_target(env):
    s3, _, w = env
    mr = {"iid": 9, "project_id": 5, "title": "ABC-42 add bus", "state": "opened", "source_branch": "feature/ABC-43-x",
          "description": "see also ABC-44 and ABC-42", "updated_at": "2026-03-01T00:00:00Z"}
    out = w.handle(raw_event(s3, "gitlab", "5!9", mr))
    assert out.links == 3
    by_to = {e["to"]["source_id"]: e for e in edges(s3, "references")}
    assert set(by_to) == {"ABC-42", "ABC-43", "ABC-44"}
    assert by_to["ABC-42"]["attributes"]["confidence"] == 1.0        # title beats description
    assert by_to["ABC-43"]["provenance"] == {"method": "rule", "rule": "jira_key_in_branch", "evidence": "ABC-43"}
    assert by_to["ABC-44"]["attributes"]["confidence"] == 0.9
    e = by_to["ABC-42"]
    assert e["pending_resolution"] and e["to"]["type"] is None and e["from"] == {"type": "Change", "source_system": "git", "source_id": "5!9"}


def test_github_pr_becomes_change_with_normalized_state_and_known_acl(env):
    s3, _, w = env
    w.handle(raw_event(s3, "github", "github:acme/pay#5", gh_pr(merged_at="2026-04-02T00:00:00Z", state="closed")))
    w.handle(raw_event(s3, "github", "github:acme/pay#6", gh_pr(number=6, state="open", private=False)))
    by_id = {e["payload"]["attributes"]["source_id"]: e["payload"] for e in published(s3, "entity.product")
             if e["payload"]["kind"] == "node"}
    assert by_id["github:acme/pay#5"]["attributes"]["change_state"] == "released"          # merged
    assert by_id["github:acme/pay#6"]["attributes"]["change_state"] == "in_review"         # opened
    a = by_id["github:acme/pay#5"]["labels"]
    assert a["acl_state"] == "known" and a["owners_only"] and a["sensitivity"] == 2         # private repo
    assert not by_id["github:acme/pay#6"]["labels"]["owners_only"]
    assert {e["to"]["source_id"] for e in edges(s3, "references")} == {"ABC-9"}


def test_github_repository_becomes_service(env):
    s3, _, w = env
    repo = {"full_name": "acme/pay", "name": "pay", "html_url": "https://github.com/acme/pay", "private": True,
            "updated_at": "2026-04-01T00:00:00Z", "description": "payments"}
    out = w.handle(raw_event(s3, "github", "github:acme/pay", repo))
    assert out.entities == 1
    p = published(s3, "entity.architecture")[0]["payload"]
    assert p["type"] == "Service" and p["attributes"]["repository_ref"] == "acme/pay"      # owner/name, as git.yml defines it


def test_ado_pull_request_uses_git_mapping(env):
    s3, _, w = env
    pr = {"pullRequestId": 12, "title": "ABC-3 fix", "status": "completed", "creationDate": "2026-06-01T00:00:00Z",
          "closedDate": "2026-06-02T00:00:00Z", "sourceRefName": "refs/heads/bugfix/ABC-4-x",
          "repository": {"name": "svc", "project": {"name": "Pay"}}}
    w.handle(raw_event(s3, "ado", "ado:Pay/svc!12", pr))
    node = next(e["payload"] for e in published(s3, "entity.product") if e["payload"]["kind"] == "node")
    assert node["attributes"]["change_state"] == "released" and node["attributes"]["source_id"] == "ado:Pay/svc!12"
    assert {e["to"]["source_id"] for e in edges(s3, "references")} == {"ABC-3", "ABC-4"}



def test_gitlab_wrapped_payload_and_commit_messages_are_linked(env):
    """The connector stores the MR with its sub-resources: {merge_request, commits, notes, approvals, diffs}."""
    s3, _, w = env
    raw = {"merge_request": {"iid": 8, "project_id": 5, "title": "Add bus", "state": "opened",
                             "source_branch": "feature/bus", "updated_at": "2026-03-01T00:00:00Z"},
           "commits": [{"id": "a1", "message": "ABC-77 wire the queue"}, {"id": "a2", "message": "tidy"}],
           "notes": [], "approvals": {}, "diffs": []}
    out = w.handle(raw_event(s3, "gitlab", "5!8", raw))
    assert out.entities == 1 and out.links == 1
    (e,) = edges(s3, "references")
    assert e["to"]["source_id"] == "ABC-77" and e["provenance"]["rule"] == "jira_key_in_commit"
    assert e["attributes"]["confidence"] == 0.9


def test_github_wrapped_payload_and_commit_messages_are_linked(env):
    s3, _, w = env
    raw = {"pull_request": gh_pr(number=9, title="Queue work", branch="feature/q"),
           "commits": [{"sha": "x", "commit": {"message": "ABC-90 add queue"}}], "reviews": []}
    out = w.handle(raw_event(s3, "github", "github:acme/pay#9", raw))
    assert out.entities == 1 and {e["to"]["source_id"] for e in edges(s3, "references")} == {"ABC-90"}
