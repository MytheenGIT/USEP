from __future__ import annotations

from common.source_document import SourceType
from config import SchedulerSettings
from scheduler import IngestionScheduler, job_id
from sync_service import SyncService
from tests.conftest import FakeConnector


async def test_one_job_per_source_and_scope(cursor_manager, raw_payload_writer, audit_writer) -> None:
    service = SyncService(
        connectors={"jira": FakeConnector(SourceType.JIRA, [], scopes=["project = A", "project = B"])},
        cursor_manager=cursor_manager,
        writer_factory=lambda _run_id, _audit: raw_payload_writer,
        audit_writer_factory=lambda _run_id: audit_writer,
    )
    scheduler = IngestionScheduler(service, SchedulerSettings(jira_interval_minutes=15))
    scheduler.start()
    try:
        jobs = {job.id: job for job in scheduler._scheduler.get_jobs()}
        assert set(jobs) == {job_id("jira", "project = A"), job_id("jira", "project = B")}
        assert jobs[job_id("jira", "project = B")].kwargs == {"scopes": ["project = B"]}
    finally:
        scheduler.shutdown()


async def test_scope_interval_override(cursor_manager, raw_payload_writer, audit_writer) -> None:
    service = SyncService(
        connectors={"jira": FakeConnector(SourceType.JIRA, [], scopes=["project = A", "project = B"])},
        cursor_manager=cursor_manager,
        writer_factory=lambda _run_id, _audit: raw_payload_writer,
        audit_writer_factory=lambda _run_id: audit_writer,
    )
    settings = SchedulerSettings(jira_interval_minutes=30, scope_interval_minutes={"jira:project = A": 5})
    scheduler = IngestionScheduler(service, settings)
    scheduler.start()
    try:
        jobs = {job.id: job for job in scheduler._scheduler.get_jobs()}
        assert jobs[job_id("jira", "project = A")].trigger.interval.total_seconds() == 5 * 60
        assert jobs[job_id("jira", "project = B")].trigger.interval.total_seconds() == 30 * 60
    finally:
        scheduler.shutdown()
