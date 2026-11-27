from __future__ import annotations

import httpx
import pytest

from servicenow.client import ServiceNowClient
from servicenow.connector import ServiceNowConnector

BASE = "https://dev1.service-now.com"


def _connector(handler, tables=("incident",), **kwargs) -> ServiceNowConnector:
    client = ServiceNowClient(BASE, "svc-user", "pw", transport=httpx.MockTransport(handler))
    return ServiceNowConnector(client, list(tables), **kwargs)


def _record(number: str, updated: str, **extra) -> dict:
    def pair(value, shown=None):
        return {"value": value, "display_value": shown if shown is not None else value}

    return {
        "sys_id": pair(f"sys{number}"), "number": pair(number), "short_description": pair("Checkout times out"),
        "description": pair("Customers see a spinner"), "state": pair("2", "In Progress"), "priority": pair("1", "1 - Critical"),
        "category": pair("software", "Software"), "assignment_group": pair("grp1", "Payments Support"), "assigned_to": pair("u1", "Pat Agent"),
        "cmdb_ci": pair("ci1", "payments-api"), "opened_at": pair("2026-11-20 08:00:00"), "closed_at": pair(""),
        "sys_updated_on": pair(updated, "26/11/2026 15:30:00"), **extra,
    }


def test_the_table_name_goes_into_a_path_so_only_plain_names_are_accepted() -> None:
    with pytest.raises(ValueError):
        _connector(lambda r: httpx.Response(200), tables=["incident/../sys_user"])
    assert _connector(lambda r: httpx.Response(200), tables=["incident", "change_request", "incident"]).scopes == ["incident", "change_request"]


def test_the_query_steps_back_a_day_and_keeps_the_admins_filter() -> None:
    connector = _connector(lambda r: httpx.Response(200), encoded_query="active=true^priority<=2")
    assert connector.build_query(None) == "active=true^priority<=2^ORDERBYsys_updated_on"
    assert connector.build_query("2026-11-26T10:00:00.000Z") == "sys_updated_on>=2026-11-25 00:00:00^active=true^priority<=2^ORDERBYsys_updated_on"


async def test_records_are_paged_filtered_by_the_cursor_and_normalized() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/now/table/incident" and request.headers["authorization"].startswith("Basic ")
        params = dict(request.url.params)
        seen.append(params)
        offset = int(params["sysparm_offset"])
        rows = [_record("INC0001", "2026-11-25 23:00:00"), _record("INC0002", "2026-11-26 11:00:00"), _record("INC0003", "2026-11-26 12:00:00")]
        return httpx.Response(200, json={"result": rows[offset : offset + 2]})

    result = await _connector(handler, page_size=2).fetch_scope("incident", "2026-11-26T10:00:00.000Z")

    assert [p["sysparm_offset"] for p in seen] == ["0", "2"] and seen[0]["sysparm_display_value"] == "all"
    assert [d.number for d in result.documents] == ["INC0002", "INC0003"]  # INC0001 is inside the one-day margin but older
    doc = result.documents[0]
    assert (doc.source_object_id, doc.source_type, doc.source_version) == ("incident:INC0002", "incident", "2026-11-26T11:00:00.000Z")
    assert (doc.state, doc.priority, doc.assignment_group, doc.assigned_to, doc.configuration_item) == ("In Progress", "1 - Critical", "Payments Support", "Pat Agent", "payments-api")
    assert doc.title == "Checkout times out" and doc.content == "Customers see a spinner" and doc.opened_at == "2026-11-20T08:00:00.000Z"
    assert doc.source_url == f"{BASE}/nav_to.do?uri=incident.do?sys_id=sysINC0002"
    assert doc.acl == {"table": "incident", "assignment_group": "Payments Support"}
    assert doc.raw_payload["record"]["number"]["value"] == "INC0002"


async def test_check_probes_every_table_and_shows_the_one_that_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/problem"):
            return httpx.Response(403, json={"error": {"message": "Insufficient rights"}, "status": "failure"})
        return httpx.Response(200, json={"result": []})

    result = await _connector(handler, tables=["incident", "problem"]).check()

    assert not result.ok and [(s.scope, s.ok) for s in result.scopes] == [("incident", True), ("problem", False)] and "403" in result.scopes[1].detail

    assert not (await _connector(lambda r: httpx.Response(200), tables=[]).check()).ok  # nothing to test with


async def test_a_refused_password_is_reported_for_each_table() -> None:
    result = await _connector(lambda r: httpx.Response(401, json={"error": {"message": "User Not Authenticated"}}), tables=["incident"]).check()
    assert not result.ok and "401" in result.scopes[0].detail
