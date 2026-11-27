"""Chooses where raw objects land: files in the repo's output folder for now, S3 once it is connected.

Both stores keep the same keys and the same encrypted bytes, so changing ``USEP_INGESTION_RAW_STORE``
from ``file`` to ``s3`` is the whole switch.
"""

from __future__ import annotations

from pathlib import Path

import boto3

from config import Settings
from usep.adapters.local_files.object_store import FileObjectStore
from usep.adapters.s3.object_store import S3ObjectStore


def make_object_store(settings: Settings) -> FileObjectStore | S3ObjectStore:
    if settings.raw_store == "s3":
        return S3ObjectStore(boto3.client("s3", region_name=settings.s3_region), settings.s3_bucket)
    return FileObjectStore(Path(settings.raw_store_dir or f"{settings.output_dir}/raw"))


def make_audit_factory(settings: Settings, session_factory, tenant_id, app_version: str):
    """``factory(trace_id) -> AuditPort``: one writer per run (trace id) or one for the console (None). The three
    backends keep the same record and hash chain, so changing ``USEP_INGESTION_AUDIT_STORE`` is the whole switch."""
    if settings.audit_store == "postgres":
        from db.ports_sql import SqlAuditWriter

        return lambda trace_id: SqlAuditWriter(session_factory, tenant_id, trace_id, app_version)
    if settings.audit_store == "s3":
        from usep.adapters.s3.audit import ObjectStoreAuditWriter

        store = S3ObjectStore(boto3.client("s3", region_name=settings.s3_region), settings.s3_bucket)
        return lambda trace_id: ObjectStoreAuditWriter(store, tenant_id, trace_id, app_version)
    from usep.adapters.local_files.audit import FileAuditWriter

    root = Path(settings.audit_dir or f"{settings.output_dir}/audit")
    return lambda trace_id: FileAuditWriter(root, tenant_id, trace_id, app_version)
