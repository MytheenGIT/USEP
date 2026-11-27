"""Jira issues: mapping, state translation, quarantine."""
import json


from tests.pipeline.helpers import (edges, jira, published, raw_event, TENANT)




def test_jira_story_becomes_requirement_with_translated_status(env):
    s3, _, w = env
    out = w.handle(raw_event(s3, "jira", "ABC-1", jira("ABC-1", "Story", "Open")))
    assert (out.entities, out.quarantined) == (1, 0)
    (ev,) = published(s3, "entity.product")
    p = ev["payload"]
    assert ev["tenant_id"] == TENANT and p["type"] == "Requirement"
    assert p["attributes"]["status"] == "draft" and "entity_id" not in p["attributes"]
    assert p["attributes"]["source_system"] == "jira" and p["attributes"]["source_id"] == "ABC-1"
    assert p["attributes"]["valid_from"] == "2026-01-02T10:00:00.000Z"


def test_jira_task_status_goes_through_project_workflow(env):
    s3, _, w = env
    w.handle(raw_event(s3, "jira", "ABC-2", jira("ABC-2", "Task", "In Review")))
    (ev,) = published(s3, "entity.product")
    assert ev["payload"]["type"] == "Change" and ev["payload"]["attributes"]["change_state"] == "in_review"


def test_unmapped_state_and_unmapped_type_are_quarantined_not_dropped(env):
    s3, _, w = env
    a = w.handle(raw_event(s3, "jira", "ABC-3", jira("ABC-3", "Task", "Blocked")))
    b = w.handle(raw_event(s3, "jira", "ABC-4", jira("ABC-4", "Spike", "Open")))
    assert a.reasons == ["Q-STATE"] and b.reasons == ["Q-UNMAPPED"]
    q = published(s3, "quarantine")
    assert {e["payload"]["reason_code"] for e in q} == {"Q-STATE", "Q-UNMAPPED"}
    assert not published(s3, "entity.product")
    stored = [json.loads(v) for k, v in s3.objects.items() if k.startswith("quarantine/")]
    assert len(stored) == 2 and all("summary" not in json.dumps(x) for x in stored)   # reason and location, no content


def test_jira_issue_does_not_reference_itself_and_lookalikes_are_ignored(env):
    s3, _, w = env
    w.handle(raw_event(s3, "jira", "ABC-20", jira("ABC-20", "Task", "Done", desc="ABC-20 itself, sABC-21, UTF-8, ABC-22")))
    assert {e["to"]["source_id"] for e in edges(s3, "references")} == {"ABC-22"}

