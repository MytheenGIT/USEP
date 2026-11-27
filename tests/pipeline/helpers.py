"""Shared helpers for the C-02 pipeline tests: building raw events and reading what the worker published."""
import json
from pathlib import Path

from usep.core.ids import uuid7
from usep.ports.event_bus import Event

ONT = Path(__file__).resolve().parents[2] / "ontology"
PINS = ["app.app-reference@0.1.0", "org.org-reference@0.1.0", "project.project-reference@0.1.0"]
TENANT = str(uuid7())
BUCKET = "usep"


def raw_event(s3, source, ref, raw, tenant=TENANT):
    body = json.dumps(raw, sort_keys=True).encode()
    key = f"raw/{source}/{ref}/abc{len(s3.objects)}.json"
    s3.objects[key] = body
    return Event(str(uuid7()), f"raw.{source}", ref, tenant, "raw.snapshot_written", 1, "2026-01-01T00:00:00.000Z", {
        "source": source, "source_type": "x", "source_ref": ref, "source_url": "https://x/" + ref,
        "snapshot_ref": f"s3://{BUCKET}/{key}", "checksum": f"abc{len(s3.objects)}" * 8,
        "retrieved_at": "2026-01-01T00:00:00Z"}, {})


def published(s3, topic):
    return [json.loads(v) for k, v in sorted(s3.objects.items()) if f"/{topic}/" in k and k.startswith("bus/")]


def jira(key, itype, status, desc="", labels=(), links=(), security=None, priority="High"):
    f = {"summary": f"{key} summary", "description": desc, "status": {"name": status}, "priority": {"name": priority},
         "issuetype": {"name": itype}, "labels": list(labels), "updated": "2026-01-02T10:00:00.000+0000",
         "project": {"key": "ABC"}, "issuelinks": list(links)}
    if security:
        f["security"] = {"name": security}
    return {"key": key, "fields": f}


def edges(s3, type_):
    return [e["payload"] for e in published(s3, "entity.product") + published(s3, "entity.architecture")
            if e["payload"]["kind"] == "edge" and e["payload"]["type"] == type_]


def gh_pr(number=5, state="open", merged_at=None, private=True, title="ABC-9 add bus", branch="feature/x"):
    return {"number": number, "title": title, "body": "details", "state": state, "merged_at": merged_at,
            "updated_at": "2026-04-01T00:00:00Z", "labels": [{"name": "Backend"}], "head": {"ref": branch},
            "base": {"ref": "main", "repo": {"full_name": "acme/pay", "private": private}}}


def sn(number, state, priority="2", **kw):
    return {"sys_id": "a" * 32, "number": number, "short_description": f"{number} summary", "description": "d",
            "state": state, "priority": priority, "sys_updated_on": "2026-05-01 10:30:00", **kw}


def ado_wi(id_, type_, state, tags="Backend; Q2"):
    return {"id": id_, "fields": {"System.TeamProject": "Pay", "System.WorkItemType": type_, "System.Title": f"WI {id_}",
                                  "System.State": state, "System.Description": "<div>do <b>it</b></div>",
                                  "System.Tags": tags, "System.ChangedDate": "2026-06-01T08:00:00.123Z"}}
