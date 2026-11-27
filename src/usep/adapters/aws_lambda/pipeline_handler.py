"""AWS Lambda entry point for the C-02 acquisition worker.

Three ways in, one code path:
  * SQS (the deployed path): S3 notifies a queue on `bus/raw.*/`, the queue triggers this function. Each SQS message body
    is an S3 notification naming event objects. The handler reads each object and handles the event. A message that fails
    is reported in `batchItemFailures`, so only it is retried, and after maxReceiveCount it lands in the dead-letter queue.
    Needs ReportBatchItemFailures on the event source mapping.
  * Direct S3 notification (no queue): the same records without the SQS envelope. A failure raises and Lambda retries
    the whole invocation. Kept for simple setups and tests.
  * Scheduled poll (EventBridge, input `{"poll": true}`): drains `raw.<family>` for each family from the committed
    offsets. A safety net for missed notifications, and the replay path (reset the offset, run the poll).
Use one mode per deployment: S3 notifications do not commit offsets, so a poll after them handles the same events again
(harmless, but wasted work). Run the poll only for replay or reconciliation.
Ontology releases: before handling, a warm container checks the `ontology.release` topic (at most every
USEP_ONTOLOGY_REFRESH_SECONDS) and switches to a new release only if it loads from the packaged ontology/ directory and
its digest matches the event. A release naming a pack version that is not in the package is refused and the current
ontology stays (fail closed); the reason is returned as `ontology_error`. Shipping a new pack version therefore still means
shipping it in the package; the event only says which of the packaged versions to use, and when. A record that started
under one release finishes under it.
A failure outside SQS raises, so Lambda retries the invocation. Handling is idempotent either way.
Ordering: a standard SQS queue does not order messages (S3 cannot notify a FIFO queue), so two snapshots of one object can be
handled out of order. Downstream must pick by `source_version`, not arrival order; set reserved concurrency to 1 or use
the poll path (ordered per partition) where strict order matters.

Config (environment): USEP_BUS_BUCKET, USEP_BUS_PREFIX (bus), USEP_BUS_PARTITIONS (16), USEP_STORE_BUCKET (default: bus
bucket), USEP_ONTOLOGY_DIR, USEP_ONTOLOGY_PINS (comma separated pack@version), USEP_ONTOLOGY_ALLOW_REFERENCE (false),
USEP_TENANT_ID (enables ontology release refresh), USEP_ONTOLOGY_REFRESH_SECONDS (60), USEP_CONSUMER_GROUP (c02-acquisition), USEP_JIRA_PROJECT_KEYS (comma separated; when set only these prefixes count as Jira keys, otherwise a
stoplist drops UTF-8, SHA-256 and similar), USEP_REPO_HOSTS (comma separated hosts whose URLs count as repositories,
for example gitlab.example.com; empty disables the repository-URL rule). Credentials come from the function's execution role.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any
from urllib.parse import unquote_plus

from usep.adapters.s3.event_bus import S3EventBus
from usep.adapters.s3.object_store import S3ObjectStore
from usep.core.errors import PipelineError
from usep.ontology_runtime import load_ontology
from usep.ontology_runtime.events import OntologyConfigCache
from usep.ontology_runtime.events import register_schemas as register_ontology_schemas
from usep.pipeline.topics import RAW_FAMILIES, register_schemas
from usep.pipeline.worker import AcquisitionWorker, Outcome
from usep.ports.event_bus import Event, SchemaRegistry, consume

_RAW_KEY = re.compile(r"^(?P<prefix>.+?)/(?P<topic>raw\.[a-z]+)/p\d+/[^/]+\.json$")
logger = logging.getLogger(__name__)
_state: dict[str, Any] = {}        # per warm container
_injected: dict[str, Any] = {}     # same, for a build with an injected client (tests): never cached


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None or v == "":
        raise PipelineError(f"environment variable {name} is required")
    return v


def build(s3_client: Any | None = None, bundle_loader: Any | None = None) -> tuple[AcquisitionWorker, S3EventBus, str]:
    """Wire the worker. Cached per container so a warm invocation reuses the S3 client and the loaded ontology.

    `bundle_loader(pins)` returns an OntologyBundle for a list of 'pack@version' pins (injectable for tests)."""
    if _state and s3_client is None:
        return _state["worker"], _state["bus"], _state["group"]
    if s3_client is not None and _injected.get("s3") is s3_client:
        return _injected["worker"], _injected["bus"], _injected["group"]
    injected = s3_client is not None
    if not injected:
        import boto3
        s3_client = boto3.client("s3")
    pins = [p.strip() for p in os.environ.get("USEP_ONTOLOGY_PINS", "").split(",") if p.strip()]
    allow_ref = os.environ.get("USEP_ONTOLOGY_ALLOW_REFERENCE", "false").lower() == "true"
    loader = bundle_loader or (lambda p: load_ontology(_env("USEP_ONTOLOGY_DIR", "ontology"), p,
                                                       allow_reference_only=allow_ref))
    bundle = loader(pins)                                       # fails closed: a bad ontology means no processing
    registry = SchemaRegistry()
    register_schemas(registry, bundle.domains)
    register_ontology_schemas(registry)
    bucket = _env("USEP_BUS_BUCKET")
    bus = S3EventBus(s3_client, bucket, registry, os.environ.get("USEP_BUS_PREFIX", "bus"),
                     int(os.environ.get("USEP_BUS_PARTITIONS", "16")))
    store = S3ObjectStore(s3_client, os.environ.get("USEP_STORE_BUCKET") or bucket)
    group = os.environ.get("USEP_CONSUMER_GROUP", "c02-acquisition")
    tenant = os.environ.get("USEP_TENANT_ID", "")
    cache = OntologyConfigCache(tenant, f"{group}-ontology", loader, initial=bundle) if tenant else None
    hosts = tuple(h.strip() for h in os.environ.get("USEP_REPO_HOSTS", "").split(",") if h.strip())
    pkeys = tuple(k.strip() for k in os.environ.get("USEP_JIRA_PROJECT_KEYS", "").split(",") if k.strip())
    worker = AcquisitionWorker(bus, store, (lambda: cache.current) if cache else (lambda: bundle),
                               repo_hosts=hosts, project_keys=pkeys)
    state = {"worker": worker, "bus": bus, "group": group, "cache": cache, "bundle": bundle, "last_refresh": 0.0, "s3": s3_client}
    if injected:
        _injected.clear()
        _injected.update(state)
    else:
        _state.update(state)
    return worker, bus, group


def _read_event(bus_client: Any, bucket: str, key: str) -> Event:
    body = bus_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    return Event(**json.loads(body))


def _handle_s3_notification(note: dict[str, Any], bus: S3EventBus, worker: AcquisitionWorker, total: Outcome) -> int:
    """Handle the raw event objects named by one S3 notification body. Returns how many events were handled."""
    n = 0
    for rec in note.get("Records", []):                          # an S3 test event has no Records: nothing to do
        s3 = rec.get("s3")
        if not s3:
            continue
        key = unquote_plus(s3["object"]["key"])
        if not _RAW_KEY.match(key):
            continue                                            # not a raw event object (offsets, other topics)
        ev = _read_event(bus._s3, s3["bucket"]["name"], key)    # noqa: SLF001 - same client the bus uses
        total.add(worker.handle(ev))
        n += 1
    return n


def _refresh_ontology(state: dict[str, Any], now: float) -> str | None:
    """Pick up a new ontology release if one was announced. Returns the refusal reason, if any."""
    cache = state.get("cache")
    if cache is None:
        return None
    every = float(os.environ.get("USEP_ONTOLOGY_REFRESH_SECONDS", "60"))
    if now - state["last_refresh"] >= every:
        state["last_refresh"] = now
        cache.refresh(state["bus"])
    return cache.last_error


def handler(event: dict[str, Any], context: Any = None, *, _s3: Any | None = None, _loader: Any | None = None,
            _now: float | None = None) -> dict[str, Any]:
    worker, bus, group = build(_s3, _loader)
    state = _state if _state else _injected
    ontology_error = _refresh_ontology(state, time.monotonic() if _now is None else _now)
    total = Outcome()
    handled = 0
    if event.get("poll"):
        for fam in RAW_FAMILIES:
            def one(e: Event) -> None:
                nonlocal handled
                total.add(worker.handle(e))
                handled += 1
            consume(bus, f"raw.{fam}", group, one, int(event.get("limit", 100)))
    failures: list[dict[str, str]] = []
    for rec in event.get("Records", []):
        if rec.get("eventSource") == "aws:sqs":
            try:
                handled += _handle_s3_notification(json.loads(rec["body"]), bus, worker, total)
            except Exception:                                    # noqa: BLE001 - retry this message only
                logger.exception("pipeline.sqs_message_failed message_id=%s", rec.get("messageId"))
                failures.append({"itemIdentifier": rec["messageId"]})
        else:
            handled += _handle_s3_notification({"Records": [rec]}, bus, worker, total)
    return {"batchItemFailures": failures, "handled": handled, "entities": total.entities, "edges": total.edges, "links": total.links,
            "evidence_only": total.evidence_only, "quarantined": total.quarantined,
            "ontology_digest": (state["cache"].current if state.get("cache") else state["bundle"]).release.digest,
            "ontology_error": ontology_error}
