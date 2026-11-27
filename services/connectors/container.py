"""Composition root: wires clients -> connectors (from the source registry) -> SyncService -> Scheduler."""

from __future__ import annotations

from config import Settings
from db.base import create_engine, create_session_factory, create_tables
from db.repository import SyncRunRepository
from common.binary_store import LocalBinaryStore
from common.interfaces.audit_writer import StructlogAuditWriter
from common.json_file_sink import JsonFileSink
from common.interfaces.cursor_manager import InMemoryCursorManager
from common.interfaces.raw_event_publisher import NullRawEventPublisher
from common.interfaces.raw_payload_writer import NullRawPayloadWriter
from common.s3.cursor_manager import S3CursorManager
from common.s3.raw_event_publisher import S3RawEventPublisher
from common.s3.raw_payload_writer import S3RawPayloadWriter
from registry import SOURCES, build_source
from scheduler import IngestionScheduler
from sync_service import SyncService


class Container:
    """Holds the long-lived singletons for one running app instance."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        engine = create_engine(settings.database_url)
        self._engine = engine
        session_factory = create_session_factory(engine)
        self.sync_run_repository = SyncRunRepository(session_factory)

        binary_store = LocalBinaryStore(f"{settings.output_dir}/binaries")
        built = {name: build_source(name, settings, binary_store) for name in SOURCES}
        connectors = {name: connector for name, (_, connector) in built.items()}

        cursor_manager, raw_payload_writer, raw_event_publisher = self._build_stores(settings)

        self.sync_service = SyncService(
            connectors=connectors,
            cursor_manager=cursor_manager,
            raw_payload_writer=raw_payload_writer,
            raw_event_publisher=raw_event_publisher,
            audit_writer=StructlogAuditWriter(),
            sync_run_repository=self.sync_run_repository,
            json_sink=JsonFileSink(settings.output_dir),
        )
        self.scheduler = IngestionScheduler(self.sync_service, settings.scheduler)

        self._clients = [client for client, _ in built.values()]

    @staticmethod
    def _build_stores(settings: Settings):
        """S3 raw store, cursor and event bus when a bucket is configured; otherwise the non-durable dev stubs."""
        s3 = settings.s3
        if not s3.bucket:
            return InMemoryCursorManager(), NullRawPayloadWriter(), NullRawEventPublisher()
        if not settings.tenant_id:
            raise ValueError("USEP_INGESTION_TENANT_ID is required when USEP_INGESTION_S3_BUCKET is set")
        import boto3  # imported here so the dev stubs need no AWS SDK

        client = boto3.client("s3", region_name=s3.region or None, endpoint_url=s3.endpoint_url or None)
        return (
            S3CursorManager(client, s3.bucket, s3.cursor_prefix),
            S3RawPayloadWriter(client, s3.bucket, s3.raw_prefix),
            S3RawEventPublisher(client, s3.bucket, settings.tenant_id, s3.bus_prefix, s3.bus_partitions),
        )

    async def init_db(self) -> None:
        await create_tables(self._engine)

    async def aclose(self) -> None:
        for client in self._clients:
            await client.aclose()
        await self._engine.dispose()
