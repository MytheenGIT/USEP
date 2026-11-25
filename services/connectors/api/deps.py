from __future__ import annotations

from fastapi import Request

from scheduler import IngestionScheduler
from sync_service import SyncService


def get_sync_service(request: Request) -> SyncService:
    return request.app.state.sync_service


def get_scheduler(request: Request) -> IngestionScheduler:
    return request.app.state.scheduler
