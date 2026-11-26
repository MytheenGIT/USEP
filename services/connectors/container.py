"""Composition root: wires clients -> connectors -> SyncService -> Scheduler.

Adding a new source connector means adding one entry here (client +
connector) -- SyncService, the scheduler and the API routes are unaffected
beyond adding one more route, matching the existing four.
"""

from __future__ import annotations

from confluence.client import ConfluenceClient
from figma.client import FigmaClient
from gitlab.client import GitLabClient
from jira.client import JiraClient
from config import Settings
from confluence.connector import ConfluenceConnector
from figma.connector import FigmaConnector
from gitlab.connector import GitLabConnector
from jira.connector import JiraConnector
from db.base import create_engine, create_session_factory, create_tables
from db.repository import SyncRunRepository
from common.binary_store import LocalBinaryStore
from common.interfaces.audit_writer import StructlogAuditWriter
from common.json_file_sink import JsonFileSink
from common.interfaces.cursor_manager import InMemoryCursorManager
from common.interfaces.raw_payload_writer import NullRawPayloadWriter
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

        jira_client = JiraClient(
            base_url=settings.jira.base_url, email=settings.jira.email, api_token=settings.jira.api_token
        )
        gitlab_client = GitLabClient(base_url=settings.gitlab.base_url, private_token=settings.gitlab.private_token)
        confluence_client = ConfluenceClient(
            base_url=settings.confluence.base_url,
            email=settings.confluence.email,
            api_token=settings.confluence.api_token,
        )
        figma_client = FigmaClient(base_url=settings.figma.base_url, access_token=settings.figma.access_token)
        binary_store = LocalBinaryStore(f"{settings.output_dir}/binaries")

        connectors = {
            "jira": JiraConnector(
                jira_client,
                base_url=settings.jira.base_url,
                jql=settings.jira.jql,
                jql_queries=settings.jira.jql_queries,
                page_size=settings.jira.page_size,
                binary_store=binary_store,
                download_attachments=settings.jira.download_attachments,
                attachment_max_bytes=settings.jira.attachment_max_bytes,
            ),
            "gitlab": GitLabConnector(
                gitlab_client, project_ids=settings.gitlab.project_ids, page_size=settings.gitlab.page_size
            ),
            "confluence": ConfluenceConnector(
                confluence_client,
                base_url=settings.confluence.base_url,
                space_keys=settings.confluence.space_keys,
                page_size=settings.confluence.page_size,
                fetch_version_history=settings.confluence.fetch_version_history,
                version_history_limit=settings.confluence.version_history_limit,
            ),
            "figma": FigmaConnector(
                figma_client,
                file_keys=settings.figma.file_keys,
                export_format=settings.figma.export_format,
                binary_store=binary_store,
                download_exports=settings.figma.download_exports,
                export_max_bytes=settings.figma.export_max_bytes,
            ),
        }

        self.sync_service = SyncService(
            connectors=connectors,
            cursor_manager=InMemoryCursorManager(),
            raw_payload_writer=NullRawPayloadWriter(),
            audit_writer=StructlogAuditWriter(),
            sync_run_repository=self.sync_run_repository,
            json_sink=JsonFileSink(settings.output_dir),
        )
        self.scheduler = IngestionScheduler(self.sync_service, settings.scheduler)

        self._clients = [jira_client, gitlab_client, confluence_client, figma_client]

    async def init_db(self) -> None:
        await create_tables(self._engine)

    async def aclose(self) -> None:
        for client in self._clients:
            await client.aclose()
        await self._engine.dispose()
