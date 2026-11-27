"""'Test connection' for one connector: sign in, then check that everything the admin entered can be read.

It asks the connector itself (``check``), so a test and a real run use the same scopes: Jira runs each JQL for one
issue, Confluence opens each space, GitLab opens each repository, Figma reads each file's metadata. Messages say what
failed and what to check. They never include the token or the request headers.
"""

from __future__ import annotations

from collections.abc import Callable

from common.client_base import ClientRuntime
from config import Settings
from console_api.connectors import build_connector
from console_api.models import ConnectionCheck
from console_api.validation import ConnectorSpec, ParsedConnector, server_credentials

MAX_SHOWN = 4


def _name(scope: str) -> str:
    return scope if len(scope) <= 50 else scope[:47] + "..."


async def check_connection(
    spec: ConnectorSpec, parsed: ParsedConnector, settings: Settings,
    runtime_for: Callable[[str, str], ClientRuntime | None] | None = None,
) -> ConnectionCheck:
    creds = parsed.credentials or server_credentials(settings, spec.key)
    if creds is None:
        return ConnectionCheck(ok=False, message=f"No {spec.label} credentials to test")
    summary = parsed.summary
    connector, client = build_connector(
        spec.key, base_url=parsed.base_url, creds=creds, targets=summary.targets, jql_queries=summary.jql_queries,
        all_member_projects=summary.all_member_projects, settings=settings,
        auth_method=summary.auth_method, encoded_query=summary.encoded_query,
        runtime=runtime_for(spec.key, parsed.base_url) if runtime_for else None,
    )
    try:
        try:
            result = await connector.check()
        except Exception:  # noqa: BLE001 - reported as a message, never raised
            return ConnectionCheck(ok=False, message=f"{spec.label}: the request failed")
        bad = [s for s in result.scopes if not s.ok]
        if bad:
            shown = "; ".join(f"'{_name(s.scope)}': {s.detail}" for s in bad[:MAX_SHOWN])
            more = f" (and {len(bad) - MAX_SHOWN} more)" if len(bad) > MAX_SHOWN else ""
            return ConnectionCheck(ok=False, message=shown + more)
        if not result.ok:
            return ConnectionCheck(ok=False, message=f"{spec.label}: {result.detail}")
        n = len(result.scopes)
        found = f". {n} {spec.target_label.lower()} reachable" if n else ""
        extra = f". {result.detail}" if spec.key == "gitlab" and summary.all_member_projects else ""
        return ConnectionCheck(ok=True, message=f"Connected{found}{extra}")
    finally:
        await client.aclose()
