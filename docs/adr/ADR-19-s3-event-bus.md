# ADR-19: S3 as the event bus (C-03)

Status: Proposed. Needs ARB acceptance. HLD 16 Table 34 names Apache Kafka with a schema registry. Kafka is not available
in this environment (the platform has S3 and SQS), so this ADR replaces that choice: S3 holds the events, SQS delivers them. The bus stays behind `usep.ports.event_bus`, so the
choice remains swappable.

## Decision
Events are objects: `bus/<topic>/p<NNN>/<uuid7>.json`. Partition is `crc32(tenant_id:key) mod N`. Consumers list from
a committed offset (`bus/_offsets/<topic>/<group>/p<NNN>.json`). Writes use a conditional put. Delivery is at least once.

## Consequences
- Kept: per-key ordering (one partition, UUID v7 order), replay (reset offset), no extra broker to run.
- Lost: push delivery (consumers poll), consumer-group rebalancing, transactional publish, sub-second latency, and
  S3 listing cost grows with volume. Keep objects small: events carry references, not payloads.
- Ordering holds across producers only while their clocks agree. Producers must run clock sync.
- Schema registry is a minimal in-process one (`SchemaRegistry`), enforcing add-only evolution. A real registry service
  is still needed (HLD C-03).
- Revisit if sustained event rate exceeds what polling can drain, or if a use case needs sub-second latency.

## Open
Object Lock/lifecycle for `bus/` and retention are platform-iac settings, not decided here.

## Delivery: S3 holds, SQS delivers
- Push (deployed path): an S3 notification on `bus/raw.` goes to a standard SQS queue, which triggers the C-02 worker
  with `ReportBatchItemFailures`. A failing message is retried alone and, after five receives, moves to a dead-letter
  queue. The queue also gives back-pressure and batching.
- Ordering: S3 cannot notify a FIFO queue, so the queue does not order messages. Two snapshots of one object can be
  handled out of order. Consumers pick by `source_version`, never arrival order. For strict order use reserved concurrency 1
  or the poll path.
- Poll: a scheduled invocation drains from committed offsets, which is the replay path (reset the offset). Use one mode per
  deployment, because notifications do not commit offsets and a later poll would handle the same events again (safe, since
  handling is idempotent).
- Later stages (fabric writer, projectors) can read the same way: one SQS queue per consumer fed from the topic prefix,
  each with its own dead-letter queue. That is also how a second consumer group is added without Kafka.
- Entity events carry an `idempotency_key` (tenant, source, id, kind, type, snapshot checksum). The fabric writer
  (C-04) must dedupe on it. It is not built yet.
- Entity events do not carry `entity_id`. The resolver and fabric writer assign it (UUID v7), so a replay cannot mint a
  second entity.
