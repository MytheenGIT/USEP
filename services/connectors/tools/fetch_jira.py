"""Read Jira issues through the Jira connector, with your credentials taken from the environment, and print what came back.

    export USEP_INGESTION_JIRA_BASE_URL=https://your-site.atlassian.net
    export USEP_INGESTION_JIRA_EMAIL=you@example.com
    read -s USEP_INGESTION_JIRA_API_TOKEN && export USEP_INGESTION_JIRA_API_TOKEN     # typed, not echoed, not in your history
    cd services/connectors && PYTHONPATH=../../src .venv/bin/python -m tools.fetch_jira "key = KAN-2"
    ... -m tools.fetch_jira 'project = "KAN"'            # a whole project
    ... -m tools.fetch_jira 'key = KAN-2' --json         # the full normalized document, including the raw Jira payload

It uses the same client and connector as the service (same sign-in, same JQL handling, same normalization), and prints the
sign-in check first. The token is never printed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx

from config import JiraSettings
from jira.client import JiraClient
from jira.connector import JiraConnector


async def run(base_url: str, email: str, token: str, jql: str, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    client = JiraClient(base_url=base_url, email=email, api_token=token, transport=transport)
    try:
        connector = JiraConnector(client, base_url=base_url, jql_queries=[jql])
        check = await connector.check()
        fetched = await connector.fetch_scope(jql, None) if check.ok else None
    finally:
        await client.aclose()
    return {"check": check, "fetched": fetched}


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print('usage: python -m tools.fetch_jira "<JQL>" [--json]', file=sys.stderr)
        return 2
    settings = JiraSettings()
    missing = [n for n, v in (("USEP_INGESTION_JIRA_BASE_URL", settings.base_url), ("USEP_INGESTION_JIRA_EMAIL", settings.email), ("USEP_INGESTION_JIRA_API_TOKEN", settings.api_token)) if not v]
    if missing:
        print(f"set {', '.join(missing)} first", file=sys.stderr)
        return 2
    result = asyncio.run(run(settings.base_url, settings.email, settings.api_token, args[0]))
    check, fetched = result["check"], result["fetched"]
    print(f"sign-in and query: {'ok' if check.ok else 'FAILED'} ({check.detail})")
    for scope in check.scopes:
        print(f"  {scope.scope}: {'ok' if scope.ok else 'FAILED'} {scope.detail}")
    if fetched is None:
        return 1
    print(f"{len(fetched.documents)} issue(s) read, {len(fetched.errors)} error(s)")
    for error in fetched.errors:
        print(f"  error: {error.object_id}: {error.error}")
    for doc in fetched.documents:
        if "--json" in argv:
            print(json.dumps(doc.model_dump(mode="json"), indent=2, ensure_ascii=False))
        else:
            print(f"- {doc.source_object_id}  [{getattr(doc, 'status', '')}]  {doc.title}\n  {doc.source_url}\n  updated {doc.source_version}, "
                  f"{len(getattr(doc, 'comments', []))} comment(s), {len(getattr(doc, 'changelog', []))} change(s), {len(getattr(doc, 'attachments', []))} attachment(s)")
    return 0 if not fetched.errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
