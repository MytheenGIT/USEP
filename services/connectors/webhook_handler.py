"""AWS Lambda entry point for source webhooks (C-01, diagram step 2 'API / webhook').

A webhook here is a doorbell, not a data feed. It proves the sender knows the shared secret, then asks the connector
Lambda for an incremental sync of that source. The payload is never parsed or stored: everything still comes from the
source's API with the integration credentials, so a forged or replayed call can at worst cause one extra sync.

Per-source check (secret in USEP_INGESTION_WEBHOOK_SECRET_<SOURCE>, from the secrets manager like the other tokens):
  github, jira, confluence   X-Hub-Signature-256 (or X-Hub-Signature): "sha256=" + HMAC-SHA256(secret, body)
  gitlab                     X-Gitlab-Token equals the secret
  ado, servicenow            X-Usep-Webhook-Token equals the secret (set as a custom header on the hook)
A source with no secret configured, or disabled in config/sources.yaml, is refused: fail closed.
Environment: USEP_CONNECTOR_FUNCTION (the connector Lambda to invoke), USEP_SOURCES_FILE (default config/sources.yaml).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

import structlog

import sources_file
from lambda_handler import _load_secrets
from registry import SOURCES

logger = structlog.get_logger(__name__)
MAX_BODY = 1_048_576
HMAC_SOURCES = {"github", "jira", "confluence"}
TOKEN_HEADER = {"gitlab": "x-gitlab-token", "ado": "x-usep-webhook-token", "servicenow": "x-usep-webhook-token"}


def _reply(code: int, message: str) -> dict[str, Any]:
    return {"statusCode": code, "headers": {"content-type": "application/json"}, "body": json.dumps({"message": message})}


def verify(source: str, headers: dict[str, str], body: bytes, secret: str) -> bool:
    if not secret:
        return False
    h = {k.lower(): v for k, v in headers.items()}
    if source in HMAC_SOURCES:
        got = h.get("x-hub-signature-256") or h.get("x-hub-signature") or ""
        want = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(got, want)
    name = TOKEN_HEADER.get(source)
    return bool(name) and hmac.compare_digest(h.get(name, ""), secret)


def handler(event: dict[str, Any], context: Any = None, *, _lambda: Any | None = None) -> dict[str, Any]:
    path = (event.get("rawPath") or event.get("path") or "").rstrip("/")
    source = (event.get("pathParameters") or {}).get("source") or path.rsplit("/", 1)[-1]
    if source not in SOURCES:
        return _reply(404, "unknown source")
    body = event.get("body") or ""
    raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()
    if len(raw) > MAX_BODY:
        return _reply(413, "payload too large")
    if _lambda is None:
        _load_secrets()
    secret = os.environ.get(f"USEP_INGESTION_WEBHOOK_SECRET_{source.upper()}", "")
    if not verify(source, event.get("headers") or {}, raw, secret):
        logger.warning("webhook.rejected", source=source)
        return _reply(401, "invalid signature")                 # same answer for a missing secret: no hint to a prober
    doc = sources_file.load(os.environ.get("USEP_SOURCES_FILE", "config/sources.yaml"))
    if not sources_file.enabled(doc, source):
        return _reply(202, "source disabled; ignored")
    client = _lambda
    if client is None:
        import boto3
        client = boto3.client("lambda")
    client.invoke(FunctionName=os.environ["USEP_CONNECTOR_FUNCTION"], InvocationType="Event",
                  Payload=json.dumps({"source": source, "mode": "sync", "trigger": "webhook"}).encode())
    logger.info("webhook.accepted", source=source)
    return _reply(202, "sync requested")
