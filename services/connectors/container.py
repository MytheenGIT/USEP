"""Composition root: wires clients -> connectors -> SyncService -> Scheduler.

Adding a new source connector means adding one entry here (client +
connector) -- SyncService, the scheduler and the API routes are unaffected
beyond adding one more route, matching the existing four.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

import structlog

from confluence.client import ConfluenceClient
from figma.client import FigmaClient
from github.client import GitHubClient
from github.connector import GitHubConnector
from gitlab.client import GitLabClient
from servicenow.client import ServiceNowClient
from servicenow.connector import ServiceNowConnector
from jira.client import JiraClient
from config import APP_VERSION, SOURCES, Settings, source_problems
from confluence.connector import ConfluenceConnector
from figma.connector import FigmaConnector
from gitlab.connector import GitLabConnector
from jira.connector import JiraConnector, build_scopes
from db.base import create_engine, create_session_factory, create_tables
from db.repository import SyncRunRepository
from common.binary_store import LocalBinaryStore
from common.json_file_sink import JsonFileSink
from urllib.parse import urlparse

from common.client_base import ClientRuntime
from common.event_publisher import LogEventPublisher
from common.memory_cursor_store import InMemoryCursorStore
from common.observer import StructlogObserver
from db.ports_sql import SqlCursorStore, SqlQuarantine, SqlRawIndex, SqlRunSnapshots
from raw_store import make_audit_factory, make_object_store
from scheduler import IngestionScheduler
from sync_service import SyncService
from usep.adapters.local_kek.key_store import LocalKeyEncryption
from usep.core.clock import SystemClock
from usep.core.errors import ConfigError
from usep.ingestion.cursor.manager import CursorManager
from usep.ingestion.raw.writer import RawPayloadWriter
from usep.ingestion.runtime.rate_limiter import RateLimiter, RateLimitKey
from usep.ingestion.runtime.retry import RetryPolicy

logger = structlog.get_logger(__name__)


def _require_ingestion_settings(settings: Settings) -> None:
    """Fail closed: no tenant, bucket or key means nothing may be stored; a selected source must be complete.

    A source nobody selected is not checked and not started: the admin may have no Jira, or no Figma.
    """
    required = [
        ("USEP_INGESTION_TENANT_ID", settings.tenant_id),
        ("USEP_INGESTION_DEV_KEK_B64", settings.dev_kek_b64),
    ]
    if settings.raw_store == "s3":
        required.append(("USEP_INGESTION_S3_BUCKET", settings.s3_bucket))
    missing = [name for name, value in required if not value]
    lines = [f"missing required setting(s): {', '.join(missing)}"] if missing else []
    for source, found in source_problems(settings).items():
        lines.append(f"{source} is selected but incomplete: " + "; ".join(found))
    if lines:
        raise ConfigError(" | ".join(lines))


def _kek(settings: Settings) -> bytes:
    try:
        return base64.b64decode(settings.dev_kek_b64, validate=True)
    except binascii.Error as exc:
        raise ConfigError("USEP_INGESTION_DEV_KEK_B64 is not valid base64") from exc


class Container:
    """Holds the long-lived singletons for one running app instance."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        _require_ingestion_settings(settings)
        tenant_id = settings.tenant_id
        assert tenant_id is not None  # checked above

        engine = create_engine(settings.database_url)
        self._engine = engine
        session_factory = create_session_factory(engine)
        self.sync_run_repository = SyncRunRepository(session_factory)

        clock = SystemClock()
        limiter = RateLimiter(clock, backfill_fraction=0.5)  # LLD 4.3: backfill lane gets half the live rate
        observer = StructlogObserver()

        def runtime(source: str, base_url: str, requests_per_second: float) -> ClientRuntime:
            account = urlparse(base_url).hostname or source
            key = RateLimitKey(tenant_id, source, account, "live")
            if not limiter.is_configured(key):  # a console run and a scheduled run on one host share one bucket
                limiter.configure(tenant_id, source, account, rate_per_second=requests_per_second)
            return ClientRuntime(
                source_system=source,
                key=key,
                policy=RetryPolicy(),  # LLD 4.3: base 2 s, doubling, cap 10 min, 5 attempts
                rate_limiter=limiter,
                clock=clock,
                observer=observer,
            )

        binary_store = LocalBinaryStore(f"{settings.output_dir}/binaries")

        # Only the sources the admin selected are built; the others do not exist as far as the service is concerned.
        connectors: dict[str, Any] = {}
        self._clients = []
        self._blocked: dict[str, str] = {}

        if settings.ado.enabled:
            cfg = settings.ado
            client = AdoClient(
                base_url=cfg.base_url, pat=cfg.pat,
                runtime=runtime("ado", cfg.base_url, cfg.requests_per_second),
            )
            self._clients.append(client)
            connectors["ado"] = AdoConnector(
                client,
                base_url=cfg.base_url,
                project_names=cfg.project_names,
            )
        if settings.jira.enabled:
            cfg = settings.jira
            client = JiraClient(
                base_url=cfg.base_url, email=cfg.email, api_token=cfg.api_token,
                runtime=runtime("jira", cfg.base_url, cfg.requests_per_second),
            )
            self._clients.append(client)
            connectors["jira"] = JiraConnector(
                client,
                base_url=cfg.base_url,
                jql_queries=build_scopes(cfg.jql, cfg.jql_queries, cfg.project_keys),
                page_size=cfg.page_size,
                binary_store=binary_store,
                download_attachments=cfg.download_attachments,
                attachment_max_bytes=cfg.attachment_max_bytes,
            )
        if settings.gitlab.enabled:
            cfg = settings.gitlab
            client = GitLabClient(
                base_url=cfg.base_url, private_token=cfg.private_token,
                runtime=runtime("gitlab", cfg.base_url, cfg.requests_per_second),
            )
            self._clients.append(client)
            connectors["gitlab"] = GitLabConnector(
                client,
                project_ids=cfg.project_ids,
                page_size=cfg.page_size,
                all_member_projects=cfg.all_member_projects,
                max_member_projects=cfg.max_member_projects,
            )
        if settings.github.enabled:
            cfg = settings.github
            client = GitHubClient(
                base_url=cfg.base_url, token=cfg.token, runtime=runtime("github", cfg.base_url, cfg.requests_per_second)
            )
            self._clients.append(client)
            connectors["github"] = GitHubConnector(
                client,
                repositories=cfg.repositories,
                page_size=cfg.page_size,
                all_member_projects=cfg.all_member_projects,
                max_member_projects=cfg.max_member_projects,
            )
        if settings.servicenow.enabled:
            cfg = settings.servicenow
            client = ServiceNowClient(
                base_url=cfg.base_url, username=cfg.username, password=cfg.password,
                runtime=runtime("servicenow", cfg.base_url, cfg.requests_per_second),
            )
            self._clients.append(client)
            connectors["servicenow"] = ServiceNowConnector(client, tables=cfg.tables, encoded_query=cfg.query, page_size=cfg.page_size)
        if settings.confluence.enabled:
            cfg = settings.confluence
            client = ConfluenceClient(
                base_url=cfg.base_url, email=cfg.email, api_token=cfg.api_token,
                runtime=runtime("confluence", cfg.base_url, cfg.requests_per_second),
            )
            self._clients.append(client)
            connectors["confluence"] = ConfluenceConnector(
                client,
                base_url=cfg.base_url,
                space_keys=cfg.space_keys,
                page_size=cfg.page_size,
                fetch_version_history=cfg.fetch_version_history,
                version_history_limit=cfg.version_history_limit,
            )
        if settings.figma.enabled:
            cfg = settings.figma
            if not cfg.dpia_approved:
                # ADR-025 / O-05: selected, but no live Figma data until the DPIA is recorded as approved.
                self._blocked["figma"] = "waiting for the DPIA sign-off (set USEP_INGESTION_FIGMA_DPIA_APPROVED=true)"
                logger.warning("figma.blocked_dpia_not_approved")
            else:
                client = FigmaClient(
                    base_url=cfg.base_url, access_token=cfg.access_token,
                    runtime=runtime("figma", cfg.base_url, cfg.requests_per_second),
                )
                self._clients.append(client)
                connectors["figma"] = FigmaConnector(
                    client,
                    file_keys=cfg.file_keys,
                    export_format=cfg.export_format,
                    binary_store=binary_store,
                    download_exports=cfg.download_exports,
                    export_max_bytes=cfg.export_max_bytes,
                )
        for name in SOURCES:
            if getattr(settings, name).filled_but_not_selected():
                logger.warning("source.filled_but_not_selected", source=name, hint=f"set USEP_INGESTION_{name.upper()}_ENABLED=true to read it")
        logger.info("sources.enabled", sources=sorted(connectors) or "none")

        raw_index = SqlRawIndex(session_factory)
        quarantine = SqlQuarantine(session_factory)
        object_store = make_object_store(settings)
        self._object_store = object_store
        key_store = LocalKeyEncryption(_kek(settings))
        event_publisher = LogEventPublisher()

        snapshots = SqlRunSnapshots(session_factory, tenant_id)
        self._snapshots = snapshots
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._sync_run_repository = self.sync_run_repository

        def writer_factory(run_id, audit):
            return RawPayloadWriter(raw_index, object_store, key_store, event_publisher, quarantine, audit, clock, tenant_id, run_id)

        audit_factory = make_audit_factory(settings, session_factory, tenant_id, APP_VERSION)

        self._writer_factory = writer_factory
        self._audit_factory = audit_factory
        self._runtime = runtime
        # The console's own actions (sign-in, configurations) share one chain, written by one writer.
        self.console_audit = audit_factory(None)

        async def record_snapshot(run_id, source: str, scopes: list[str]) -> None:
            await snapshots.record(
                run_id,
                source,
                {
                    "scopes": scopes,
                    "source_settings": getattr(settings, source).model_dump(mode="json"),
                    "cursor_overlap_seconds": settings.cursor_overlap_seconds,
                    "app_version": APP_VERSION,
                },
            )

        self.sync_service = SyncService(
            connectors=connectors,
            cursor_manager=CursorManager(
                SqlCursorStore(session_factory, tenant_id), overlap_seconds=settings.cursor_overlap_seconds
            ),
            writer_factory=writer_factory,
            audit_writer_factory=audit_factory,
            record_snapshot=record_snapshot,
            sync_run_repository=self.sync_run_repository,
            json_sink=JsonFileSink(settings.output_dir) if settings.json_sink_enabled else None,
        )
        self.scheduler = IngestionScheduler(self.sync_service, settings.scheduler)

    def runtime_for(self, source: str, base_url: str) -> ClientRuntime:
        """Rate limit and retry for a client built outside the container (the admin console's)."""
        return self._runtime(source, base_url, getattr(self.settings, source).requests_per_second)

    def new_sync_service(
        self, connectors: dict[str, Any], *, json_sink: JsonFileSink | None = None, snapshot_extra: dict[str, dict[str, Any]] | None = None
    ) -> SyncService:
        """A service for one console configuration: the same writer, raw store and audit as everything else, but
        cursors that start empty, so the whole configuration is read in full and the graph is complete."""
        extra = snapshot_extra or {}

        async def record_snapshot(run_id, source: str, scopes: list[str]) -> None:
            await self._snapshots.record(run_id, source, {"scopes": scopes, "app_version": APP_VERSION, **extra.get(source, {})})

        return SyncService(
            connectors=connectors,
            cursor_manager=CursorManager(InMemoryCursorStore(), overlap_seconds=0),
            writer_factory=self._writer_factory,
            audit_writer_factory=self._audit_factory,
            record_snapshot=record_snapshot,
            sync_run_repository=self._sync_run_repository,
            json_sink=json_sink,
        )

    def source_overview(self) -> list[dict[str, Any]]:
        """For every source: whether the admin selected it, whether it is running, its scopes, and why it is not."""
        running = self.sync_service.available_sources
        return [
            {
                "source": name,
                "enabled": getattr(self.settings, name).enabled,
                "running": name in running,
                "scopes": self.sync_service.scopes(name) if name in running else [],
                "blocked_reason": self._blocked.get(name),
            }
            for name in SOURCES
        ]

    async def check_object_store(self) -> None:
        """Raise if the raw store cannot be used; log what write-once protection it lacks."""
        for warning in await self._object_store.check():
            logger.warning("raw_store.write_once_protection", store=self.settings.raw_store, detail=warning)
        logger.info("raw_store.ready", store=self.settings.raw_store)

    async def init_db(self) -> None:
        await create_tables(self._engine)

    async def aclose(self) -> None:
        for client in self._clients:
            await client.aclose()
        await self._engine.dispose()
