"""ServiceNow, ADO work items, Figma, and Jira incidents."""
import json


from tests.pipeline.helpers import (ado_wi, jira, published, raw_event, sn)




def test_servicenow_incident_and_change_translate_codes(env):
    s3, _, w = env
    w.handle(raw_event(s3, "servicenow", "INC0010001", sn("INC0010001", "6", "1")))
    w.handle(raw_event(s3, "servicenow", "CHG0030001", sn("CHG0030001", "-1", sys_class_name="change_request")))
    inc = published(s3, "entity.operations")[0]["payload"]
    assert inc["type"] == "Incident" and inc["attributes"]["severity"] == "sev1" and inc["attributes"]["status"] == "resolved"
    assert inc["attributes"]["valid_from"] == "2026-05-01T10:30:00.000Z" and inc["labels"]["acl_state"] == "unknown"
    chg = next(e["payload"] for e in published(s3, "entity.product") if e["payload"]["type"] == "Change")
    assert chg["attributes"]["change_state"] == "in_progress"


def test_servicenow_unknown_code_and_table_are_quarantined(env):
    s3, _, w = env
    a = w.handle(raw_event(s3, "servicenow", "INC0010002", sn("INC0010002", "99")))
    b = w.handle(raw_event(s3, "servicenow", "PRB0000001", sn("PRB0000001", "1")))
    assert a.reasons == ["Q-STATE"] and b.reasons == ["Q-PARSE"]


def test_ado_work_items_map_by_type_and_state(env):
    s3, _, w = env
    w.handle(raw_event(s3, "ado", "Pay#1", ado_wi(1, "User Story", "Active")))
    w.handle(raw_event(s3, "ado", "Pay#2", ado_wi(2, "Bug", "Resolved")))
    q = w.handle(raw_event(s3, "ado", "Pay#3", ado_wi(3, "Test Case", "New")))
    by_id = {e["payload"]["attributes"]["source_id"]: e["payload"] for e in published(s3, "entity.product")}
    assert by_id["Pay#1"]["type"] == "Requirement" and by_id["Pay#1"]["attributes"]["status"] == "approved"
    assert by_id["Pay#2"]["type"] == "Change" and by_id["Pay#2"]["attributes"]["change_state"] == "in_review"
    assert q.reasons == ["Q-UNMAPPED"]


def test_figma_file_is_evidence_only_with_text(env):
    s3, _, w = env
    raw = {"name": "Checkout v2", "version": "9", "lastModified": "2026-07-01T00:00:00Z",
           "document": {"children": [{"type": "FRAME", "children": [{"type": "TEXT", "characters": "Pay now"}]}]}}
    out = w.handle(raw_event(s3, "figma", "FILEKEY1", raw))
    assert (out.evidence_only, out.quarantined) == (1, 0)
    ev = json.loads(next(v for k, v in s3.objects.items() if k.startswith("evidence/figma")))
    assert ev["source_id"] == "FILEKEY1" and "Pay now" in ev["text"]


def test_jira_incident_priority_and_status_are_translated(env):
    s3, _, w = env
    w.handle(raw_event(s3, "jira", "ABC-30", jira("ABC-30", "Incident", "In Progress", priority="High")))
    a = published(s3, "entity.operations")[0]["payload"]["attributes"]
    assert (a["severity"], a["status"]) == ("sev2", "mitigated")

