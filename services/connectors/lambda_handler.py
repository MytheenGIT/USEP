"""AWS Lambda entry point for the source connectors (C-01).

One function image, one source per invocation. EventBridge Scheduler passes `{"source": "jira"}` (the schedule per
source replaces the APScheduler jobs of the long-running service). Each run:
  read cursor (S3) -> fetch from the source -> write raw snapshot (S3, immutable) -> publish raw.<source> event (S3 bus)
  -> move the cursor only after every event is acknowledged.
A failed run leaves the cursor where it was, so the next invocation repeats the work; snapshots and events are
idempotent. `sync_source` returns a FAILED result rather than raising, so the handler raises to make Lambda (and the
alarm on Errors) see it.

Environment: the same USEP_INGESTION_* variables as the service (config.py). USEP_INGESTION_S3_BUCKET and
USEP_INGESTION_TENANT_ID are required here: a Lambda has no disk, so the dev stubs would lose everything.
USEP_INGESTION_SECRETS_ARN (optional) names a Secrets Manager secret holding a JSON object of further USEP_INGESTION_*
variables (tokens), loaded before settings. Never put tokens in plain environment variables or in Git.
Lambda timeout bounds a run; a large backfill is many invocations, each resuming from the cursor.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import structlog

from common.interfaces.audit_writer import StructlogAuditWriter
from common.s3.cursor_manager import S3CursorManager
from common.s3.object_index import S3ObjectIndex
from common.s3.raw_event_publisher import S3RawEventPublisher
from common.s3.raw_payload_writer import S3RawPayloadWriter
from common.sync_models import SyncStatus
from config import Settings
from reconcile import Reconciler
from registry import SOURCES, build_source
from sync_service import SyncService

logger = structlog.get_logger(__name__)


class SyncFailed(RuntimeError):
    pass


class ReconcileProblem(RuntimeError):
    pass


def _load_secrets(client: Any | None = None) -> None:
    arn = os.environ.get("USEP_INGESTION_SECRETS_ARN")
    if not arn:
        return
    if client is None:
        import boto3
        client = boto3.client("secretsmanager")
    values = json.loads(client.get_secret_value(SecretId=arn)["SecretString"])
    for k, v in values.items():
        if k.startswith("USEP_INGESTION_"):
            os.environ.setdefault(k, str(v))             # an explicit environment variable wins


def build_connector(source: str, settings: Settings):
    """Build only the requested connector and its client: a Jira run needs no GitLab token."""
    return build_source(source, settings)


MODES = ("sync", "full", "reconcile")


def _stores(s3_client: Any, settings: Settings):
    s3 = settings.s3
    return (S3CursorManager(s3_client, s3.bucket, s3.cursor_prefix),
            S3RawPayloadWriter(s3_client, s3.bucket, s3.raw_prefix),
            S3RawEventPublisher(s3_client, s3.bucket, settings.tenant_id, s3.bus_prefix, s3.bus_partitions),
            S3ObjectIndex(s3_client, s3.bucket, s3.index_prefix))


async def run(source: str, settings: Settings, s3_client: Any, connector_factory=build_connector, mode: str = "sync",
              scopes: list[str] | None = None) -> dict[str, Any]:
    """One invocation. Modes:
      sync       incremental from the stored cursor (default; also the first backfill, capped per run)
      full       re-read every object in the scope, ignoring the cursor: picks up permission changes the source does not
                 stamp with an updated time. Never moves the cursor backwards.
      reconcile  list what the source holds now and tombstone what was landed earlier but is gone.
    """
    s3 = settings.s3
    if not s3.bucket or not settings.tenant_id:
        raise ValueError("USEP_INGESTION_S3_BUCKET and USEP_INGESTION_TENANT_ID are required")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    client, connector = connector_factory(source, settings)
    cursors, writer, publisher, index = _stores(s3_client, settings)
    try:
        if mode == "reconcile":
            rec = await Reconciler({source: connector}, index, publisher, settings.reconcile_max_missing_fraction
                                   ).reconcile_source(source, scopes)
            out = {"source": source, "mode": mode, **rec.as_dict()}
            if rec.problems:                          # refused or unreadable scopes: make the alarm on Errors see it
                raise ReconcileProblem(f"{source} reconcile: " + "; ".join(f"{p.scope}: {p.detail}" for p in rec.problems))
            return out
        service = SyncService(
            connectors={source: connector}, cursor_manager=cursors, raw_payload_writer=writer,
            raw_event_publisher=publisher, audit_writer=StructlogAuditWriter(), object_index=index,
            initial_cursor=settings.backfill_since or None,
            max_documents_per_scope=settings.max_documents_per_scope or None,
        )
        result = await service.sync_source(source, scopes=scopes, full=(mode == "full"))
    finally:
        await client.aclose()
    if result.status == SyncStatus.FAILED:
        raise SyncFailed(f"{source} sync failed: {'; '.join(result.errors)}")
    # PARTIAL (objects failed, a scope was skipped, or the run cap was reached) is not raised: the cursor stayed behind
    # the failed objects and behind the cap, so the next run continues exactly there. Counts are returned for alarming.
    return {"source": source, "mode": mode, "status": result.status.value, "documents": result.documents_count,
            "object_errors": len(result.object_errors), "truncated_scopes": result.truncated_scopes,
            "cursors": result.cursors}


def handler(event: dict[str, Any], context: Any = None, *, _s3: Any | None = None, _settings: Settings | None = None,
            _connector_factory=build_connector) -> dict[str, Any]:
    source = (event or {}).get("source") or os.environ.get("USEP_INGESTION_SOURCE", "")
    if source not in SOURCES:
        raise ValueError(f"event must carry source, one of {SOURCES}")
    if _settings is None:
        _load_secrets()
    settings = _settings or Settings()
    s3_client = _s3
    if s3_client is None:
        import boto3
        s3_client = boto3.client("s3", region_name=settings.s3.region or None,
                                 endpoint_url=settings.s3.endpoint_url or None)
    scope = (event or {}).get("scope")
    out = asyncio.run(run(source, settings, s3_client, _connector_factory, mode=(event or {}).get("mode", "sync"),
                          scopes=[scope] if scope else None))
    logger.info("connector.lambda.done", **out)
    return out
