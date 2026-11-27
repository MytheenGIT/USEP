"""Transactional outbox relay (diagram step 10). Moves committed changes from the outbox to the bus, at least once.

A row is marked published only after the bus accepted it. A crash between the two republishes the row, so every payload
carries an `idempotency_key` derived from the outbox id and consumers dedupe on it. A row that keeps failing is marked dead
after `max_attempts` and counted in `OutboxStatus`; it is never retried forever and never silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass

from usep.ports.event_bus import EventBus
from usep.ports.fabric_store import FabricStore


@dataclass
class RelayResult:
    published: int = 0
    failed: int = 0


class OutboxRelay:
    def __init__(self, store: FabricStore, bus: EventBus, batch_size: int = 100, max_attempts: int = 5) -> None:
        self._store, self._bus, self._n, self._max = store, bus, batch_size, max_attempts

    def run_once(self) -> RelayResult:
        res = RelayResult()
        with self._store.claim_outbox(self._n, self._max) as batch:
            for row in batch.rows:
                try:
                    payload = {**row.payload, "idempotency_key": f"outbox-{row.outbox_id}"}
                    self._bus.publish(row.topic, row.key, row.type, row.tenant_id, payload,
                                      {"idempotency_key": payload["idempotency_key"]})
                except Exception as exc:  # noqa: BLE001 - any bus failure is retried later; order of later rows is kept
                    batch.mark_failed(row.outbox_id, f"{type(exc).__name__}: {exc}"[:500])
                    res.failed += 1
                    break                                   # keep id order: do not publish past a failed row
                batch.mark_published(row.outbox_id)
                res.published += 1
        return res

    def drain(self, max_rounds: int = 1000) -> RelayResult:
        total = RelayResult()
        for _ in range(max_rounds):
            r = self.run_once()
            total.published += r.published
            total.failed += r.failed
            if r.published == 0 or r.failed:
                break
        return total
