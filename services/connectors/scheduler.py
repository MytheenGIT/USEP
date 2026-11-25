"""Periodic source synchronization.

Each source gets its own interval job that calls SyncService.sync_source.
The same SyncService method backs the manual-trigger API routes, so
"scheduled trigger" and "manual trigger" are just two callers of one path.
"""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import SchedulerSettings
from sync_service import SyncService

logger = structlog.get_logger(__name__)


class IngestionScheduler:
    def __init__(self, sync_service: SyncService, settings: SchedulerSettings) -> None:
        self._sync_service = sync_service
        self._settings = settings
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        if not self._settings.enabled:
            logger.info("scheduler.disabled")
            return

        interval_minutes = {
            "jira": self._settings.jira_interval_minutes,
            "gitlab": self._settings.gitlab_interval_minutes,
            "confluence": self._settings.confluence_interval_minutes,
            "figma": self._settings.figma_interval_minutes,
        }

        for source in self._sync_service.available_sources:
            minutes = interval_minutes.get(source, 60)
            self._scheduler.add_job(
                self._sync_service.sync_source,
                trigger=IntervalTrigger(minutes=minutes),
                args=[source],
                id=f"sync-{source}",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info("scheduler.job_registered", source=source, interval_minutes=minutes)

        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def trigger_now(self, source: str):
        """Manual trigger: runs the same job function immediately, out of band."""
        return await self._sync_service.sync_source(source)
