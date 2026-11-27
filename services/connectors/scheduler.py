"""Periodic source synchronization, one job per source and scope.

Every configured scope (JQL query, repository, space, file) gets its own
interval job calling ``SyncService.sync_source(source, scopes=[scope])``.
The same method backs the manual-trigger API routes, so "scheduled" and
"manual" are two callers of one path; SyncService's per-scope lock stops
them from running the same scope at once.
"""

from __future__ import annotations

import hashlib

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import SchedulerSettings
from sync_service import SyncService

logger = structlog.get_logger(__name__)


def job_id(source: str, scope: str) -> str:
    # Scopes can be long URLs or JQL; a short hash keeps job ids readable and unique.
    return f"sync-{source}-{hashlib.sha1(scope.encode()).hexdigest()[:10]}"


class IngestionScheduler:
    def __init__(self, sync_service: SyncService, settings: SchedulerSettings) -> None:
        self._sync_service = sync_service
        self._settings = settings
        self._scheduler = AsyncIOScheduler()

    def _interval_minutes(self, source: str, scope: str) -> int:
        """Per-scope override if configured, else the source's default interval."""
        override = self._settings.scope_interval_minutes.get(f"{source}:{scope}")
        if override:
            return int(override)
        return int(getattr(self._settings, f"{source}_interval_minutes", 60))

    def _register_jobs(self) -> None:
        """One interval job per source and scope. Safe to call again: new scopes get jobs, gone ones lose theirs."""
        wanted: set[str] = set()
        for source in self._sync_service.available_sources:
            scopes = self._sync_service.scopes(source)
            if not scopes:
                logger.info("scheduler.no_scopes", source=source)
            for scope in scopes:
                minutes = self._interval_minutes(source, scope)
                wanted.add(job_id(source, scope))
                self._scheduler.add_job(
                    self._sync_service.sync_source,
                    trigger=IntervalTrigger(minutes=minutes, jitter=self._settings.jitter_seconds or None),
                    args=[source],
                    kwargs={"scopes": [scope]},
                    id=job_id(source, scope),
                    name=f"{source}: {scope}",
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                )
                logger.info("scheduler.job_registered", source=source, scope=scope, interval_minutes=minutes)
        for job in self._scheduler.get_jobs():
            if job.id.startswith("sync-") and job.id not in wanted:
                self._scheduler.remove_job(job.id)
                logger.info("scheduler.job_removed", job=job.name)

    async def _refresh(self) -> None:
        await self._sync_service.refresh_scopes()
        self._register_jobs()

    def start(self) -> None:
        if not self._settings.enabled:
            logger.info("scheduler.disabled")
            return

        self._register_jobs()
        if self._sync_service.has_dynamic_scopes:
            self._scheduler.add_job(
                self._refresh,
                trigger=IntervalTrigger(minutes=self._settings.scope_refresh_minutes),
                id="refresh-scopes",
                name="refresh scopes",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def trigger_now(self, source: str, scopes: list[str] | None = None):
        """Manual trigger: runs the same job function immediately, out of band."""
        return await self._sync_service.sync_source(source, scopes=scopes)
