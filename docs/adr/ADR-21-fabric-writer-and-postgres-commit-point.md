# ADR-21: Fabric writer and the PostgreSQL commit point (C-04)

Status: Proposed. Needs ARB acceptance. HLD names PostgreSQL as the authoritative store; this ADR fixes how the writer
commits to it and how committed changes reach the projectors. Nothing here is deployed.

## Context
C-02 publishes `entity.<domain>` candidates (nodes, edges, pending links) and a `retraction` topic. Nothing commits them:
`usep.graph.entity_events` rebuilds a graph in memory, which is not authoritative and cannot carry authorization. The write
rules (`CLAUDE.md`, ADR-05) say only the fabric writer inserts into fact tables, and nothing writes to a projection store
directly. The diagram's step 9 (atomic commit) and step 10 (transactional outbox) are not built.

## Decision
1. **One writer, one commit.** `usep.fabric.FabricWriter` handles one event in one PostgreSQL transaction. It commits the
   current entity state, the assertion history, the identity binding, resolved or pending edges, the idempotency key and the
   outbox rows together, or none of them.
2. **Hexagonal split.** Rules live in `usep/fabric/` and see only the port `usep/ports/fabric_store.py`. PostgreSQL is
   `usep/adapters/postgres/` (psycopg 3, plain SQL migrations). The same behaviour tests run against an in-memory store
   and a real PostgreSQL.
3. **Idempotency.** `(tenant_id, idempotency_key)` is claimed first inside the transaction. A repeat returns `duplicate`
   and writes nothing, so at-least-once delivery is safe. A rolled-back transaction releases the claim.
4. **Ordering.** Events are not ordered across producers. A node replaces current state only if its
   `(valid_from, source_version)` is newer than the state it would replace. Otherwise it is recorded in history as not
   applied (`stale`) and state is unchanged. Sensitivity never goes down on a node update (evidence contract). A retraction
   stops anything not newer than it from reviving the entity.
5. **History is append-only.** Every accepted assertion is kept with `applied` true or false. State rows are a
   projection of that history that can be replayed; a retraction marks state and edges, it deletes nothing.
6. **Identity until the resolver exists.** The resolver (step 6) is not built, so one entity is created per
   `(tenant, source_system, source_id)`, bound in `source_identity`. When the resolver arrives it adds aliases and merges
   through the same writer; the writer never merges two source identities itself. A record whose type disagrees with the
   type already bound to its identity is rejected (`type_conflict`), never overwritten: an Issue is not a Service.
7. **Edges.** An edge is keyed by `(type, from, to)`. If either end has no entity yet, it is stored pending with the
   source reference and is linked in the transaction that commits the missing node (a type named on the reference must
   match). An end that does not match is never guessed.
8. **Bad input is parked, not fatal.** An event that cannot be parsed or that conflicts is written to `fabric_rejected`
   with a reason code and the event id, never its content in logs, and the consumer carries on. Only infrastructure
   errors stop the consumer, so the event is retried.
9. **Authorization data travels with the row.** `tenant_id` is on every table and in every key. Row-level security
   (`app.tenant_id`, `FORCE`) enforces it for the writer and any reader role. Sensitivity, ACL state, owners-only and ACL
   are stored on state and edges and repeated in outbox payloads, so a projector filters without reading back.
10. **Transactional outbox.** The outbox row is inserted in the same transaction as the change. A relay claims unpublished
    rows (`FOR UPDATE SKIP LOCKED`, in id order), publishes them to the bus topics `commit.entity` and `commit.edge`, and marks
    them published. A crash between publish and mark republishes: delivery is at least once, and each payload carries an
    `idempotency_key` derived from the outbox id. A row that fails `max_attempts` times is marked dead and counted, not retried
    forever. The outbox has no row-level security because the relay is cross-tenant; its role should hold rights on the outbox
    only.

## Consequences
- Kept: authoritative state is committed before anything downstream hears of it; projectors can always be rebuilt from
  PostgreSQL; replay is safe.
- Lost: strict ordering across sources, resolved by the newest-wins rule (one lost update is possible if a source
  reports a wrong `valid_from`). The relay holds a transaction open while publishing, so batches stay small and the relay
  scales by partitioning later, not by many workers per row.
- A single writer transaction per event is simple but not the fastest; batching is a later optimization.

## Not decided here
- Ownership beyond ACL (the "every Service has exactly one owning Team" check) is for the resolver and steward flow.
- Projection watermarks and lag (`projector`, `last_outbox_id`) belong to the projectors; the outbox reports pending, dead and
  oldest-age counts for now.
- Roles, secrets, backups, RDS settings and the `pgvector` extension are platform-iac work. No IaC is written here.
- Connection pooling (RDS Proxy or pgbouncer) is not designed; the adapter opens a connection per transaction.
- Retention of `fabric_rejected` and assertion history.
