"""``Observer`` that writes every outbound call, wait, retry and dead letter as a structured log
line (spec 7.2: external calls record endpoint, status, latency and retry count). OpenTelemetry
export is a later step; the logs go to the same place the rest of the service logs to.
"""

from __future__ import annotations

from datetime import datetime

import structlog

logger = structlog.get_logger("usep.source_call")


class StructlogObserver:
    def attempt(
        self, *, source_system: str, endpoint: str, status: str | None, latency_ms: float, retry_count: int,
        error_type: str | None,
    ) -> None:
        logger.info(
            "source_call", source=source_system, endpoint=endpoint, status=status,
            latency_ms=round(latency_ms, 1), retry_count=retry_count, error_type=error_type,
        )

    def rate_wait(self, *, source_system: str, lane: str, seconds: float) -> None:
        logger.info("source_rate_wait", source=source_system, lane=lane, seconds=round(seconds, 3))

    def retry(self, *, source_system: str, endpoint: str, reason: str, delay_s: float) -> None:
        logger.warning("source_retry", source=source_system, endpoint=endpoint, reason=reason, delay_s=round(delay_s, 3))

    def deferred(self, *, source_system: str, endpoint: str, retry_at: datetime) -> None:
        logger.warning("source_deferred", source=source_system, endpoint=endpoint, retry_at=retry_at.isoformat())

    def dead_letter(self, *, source_system: str, endpoint: str, reason: str) -> None:
        logger.error("source_dead_letter", source=source_system, endpoint=endpoint, reason=reason)
