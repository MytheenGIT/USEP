# Serverless connector path: parked, and what porting it needs

Status: open decision. Written when `ontology-ui-graphify` was rebased onto `main`.

## What happened
`main` reworked how connectors land data (`usep.ingestion`: encrypted raw objects, a raw index, a reference-only
`RawObjectPublished` event on `EventBusPort.publish_raw`). The branch had built a different landing path on the old code:
plain snapshots in S3 plus a `raw.<family>` event carrying `snapshot_ref`, `checksum`, `source_url`, `scope`, `source_version` and
`acl`, which the C-02 pipeline reads. Both cannot be merged line by line, so on the rebase `main`'s connector code won, and the
branch's serverless path was left in the tree without a working base.

## What is parked (code in the tree, tests skipped with this file as the reason)
| Piece | Files | Tests parked |
|---|---|---|
| Lambda entry (sync, full, reconcile) | `services/connectors/lambda_handler.py` | `test_lambda_handler.py` |
| Webhook entry | `webhook_handler.py` | `test_webhook_handler.py` |
| Source registry, per-source factories | `registry.py`, `*/factory.py` | `test_registry.py` |
| Sources file (`config/sources.yaml`) | `sources_file.py` | `test_sources_file.py` |
| Snapshot writer, raw event publisher, object index, cursor on S3 | `common/s3/*`, `common/interfaces/{raw_event_publisher,object_index}.py` | `test_s3_ingestion.py` |
| Backfill start, per-run cap, full refresh | (was in `sync_service.py`) | `test_sync_modes.py` |
| Reconcile and tombstones | `reconcile.py` | (in `test_lambda_handler.py`) |

Retired as superseded by `main`'s own connectors and client runtime: `test_client_base.py`, `test_new_connectors.py`,
`test_new_clients_http.py`. They tested the branch's versions of the GitHub, ServiceNow and ADO clients, which `main` replaced. What
is lost is HTTP-level coverage of `main`'s clients (auth header, path, query string); worth rewriting against `main`'s methods.

## What `main` does not have that the pipeline relies on
1. **Deletions reaching the graph.** `main` already reconciles a scope and, after a second confirmation, tombstones an object
   and crypto-shreds it (`usep.ingestion.cursor.reconcile`). It does not tell anyone downstream. The branch's chain was
   tombstone event → pipeline `retraction` topic → fabric writer retracts; only the first link is missing.
2. **A way for the pipeline to read raw objects**, which `main` encrypts per object.
3. **Permission changes on unchanged content.** `main` skips an object whose content hash is unchanged, so a new ACL is not
   announced.
4. **Backfill start and a per-run cap**, so a first run on a large Jira cannot run unbounded, and a **full refresh** mode.
5. **Webhooks**, and a **Lambda entry** that runs one source per invocation (`platform-iac/lambda/template.yaml`).

## Decisions
Items 1 to 3 are decided in a proposal: [ADR-24](../adr/ADR-24-pipeline-access-to-raw-objects.md) (a narrow raw reader with
separated roles and audited decrypts, one event mapping at publish time, `source_url` on the contract, a tombstone event, and an
ACL digest so permission changes are re-announced). It needs ARB and security-architect acceptance, and the ingestion team's review
because it adds small fields to `usep.ingestion`. Items 4 and 5 need no new decision.

## Suggested order
Follow the implementation order in ADR-24, then:
1. Port backfill, the per-run cap and full refresh into `main`'s `SyncService`.
2. Re-point `lambda_handler.py` and `webhook_handler.py` at `main`'s container and un-skip their tests.

The old implementation is in git history (`origin/ontology-ui-graphify` before the rebase was pushed) for reference.
