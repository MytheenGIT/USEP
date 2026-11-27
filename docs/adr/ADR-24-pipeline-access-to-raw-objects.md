# ADR-24: How the pipeline reads raw objects (and hears about deletions)

Status: Proposed. Needs ARB acceptance and security-architect review (it decides who may decrypt raw data).
Number: ADR-22 is cited in `usep/adapters/vault/resolver.py` (Vault and SPIFFE, not yet in `docs/adr`) and ADR-023 is in the
decisions register (evidence snapshots), so this one takes 24.
Builds on: `usep.ingestion` (raw writer, index, key store), ADR-19 (S3 event bus), ADR-21 (fabric writer), the evidence contract.

## Context
`main`'s ingestion layer lands every source object as an **encrypted raw object** and announces it with a reference-only
event:

- Object: `raw/{tenant}/{source}/{scope}/{type}/{id}/{content_hash}.json`, AES-256-GCM (`nonce || ciphertext`), AAD =
  `object_key + tenant_id`. The payload is the canonical JSON of the raw record without the `_usep` envelope.
- Key: one data key per object, wrapped by the tenant's KMS key-encryption key. The wrapped key and `kek_id` live in the **raw
  index row**, not in the object. Reconciliation can **tombstone** an object, which clears the wrapped key (crypto-shred).
- Event `RawObjectPublished` (via `EventPublisherPort.publish_raw`): tenant, source, scope, object type and id, `object_key`,
  `content_hash`, run, checkpoint, `source_version`, `extracted_at`, `acl_ref`, `source_acl`. No payload, no `source_url`.

The C-02 pipeline (`usep.pipeline`) was written against a different contract: a `raw.<family>` event carrying `snapshot_ref`,
`checksum`, `source_url`, `scope`, `source_version`, `acl`, and a **plaintext** snapshot it reads with `ObjectStore.get(ref)`.
Nothing connects the two, so the pipeline cannot run on what `main`'s connectors produce. The gaps:

1. The pipeline cannot read the objects: they are encrypted and the key is in the index.
2. The events differ in shape, and `source_url` is missing.
3. Reconciliation shreds a deleted object but tells nobody downstream, so a deleted record stays in the graph.
4. A permission change that leaves the payload unchanged is `skipped_unchanged`, so the new ACL is never announced.

## Decision
1. **A narrow raw reader, not a shared key.** `usep.ingestion.raw.reader.RawReader.read(ref) -> bytes` looks up the index row,
   unwraps the data key through `KeyEncryptionPort`, decrypts with the same AAD, and verifies `sha256(canonical bytes) ==
   content_hash`. The pipeline depends only on a small port, `SnapshotReader.read(snapshot_ref)`; the reader is the one place that
   touches keys. A tombstoned or shredded object returns `Erased`, never an error.
2. **Separated roles.** Writers (connectors) may encrypt, wrap and put under `raw/`; they cannot unwrap. The pipeline worker may
   read `raw/`, unwrap, and read the index; it cannot write `raw/` or wrap new keys. The KMS key policy conditions both on the
   encryption context `tenant_id`, so a role cannot decrypt another tenant's data. No other role decrypts raw data.
3. **Every decrypt is audited** (`raw.read`: tenant, object key, content hash, caller; never content) in addition to KMS's own log.
4. **Plaintext lives in memory only.** The pipeline decrypts, redacts, classifies and writes evidence (already redacted). It never
   stores the decrypted raw payload, and quarantine entries carry reason codes and field names, not content (unchanged).
5. **One event mapping, at publish time.** An `EventPublisherPort` adapter for the ADR-19 bus (`S3RawEventPublisher`) maps
   `RawObjectPublished` to the pipeline's `raw.<family>` event: `snapshot_ref = "raw://" + object_key`, `checksum = content_hash`,
   `source_ref = object_id`, `source_type = object_type`, `scope = scope_id`, `retrieved_at = extracted_at`, `acl = source_acl`,
   `source_version` as is. The pipeline's schema and topic names do not change.
6. **`source_url` is added to the contract.** The connector's `_usep` envelope gets `source_url`; `RawObjectPublished` gets an
   optional `source_url` (add-only). An event without one is quarantined `Q-SCHEMA` by the pipeline, never guessed.
7. **Deletions travel as events.** When reconciliation tombstones an object it also publishes `tombstone.<family>` through a new
   `EventPublisherPort.publish_tombstone(...)` (add-only; fields as `TOMBSTONE_REQUIRED`). The pipeline re-announces it as
   `retraction` (built) and the fabric writer retracts the entity and its edges (built, ADR-21). Order inside reconcile: publish
   the tombstone event first, then crypto-shred, so a failed publish retries while the data is still readable.
8. **A permission change is re-announced even if the content did not change.** The raw index row gets an `acl_digest`. When a
   re-read object has the same `content_hash` but a different ACL digest, the writer does not write a new object; it updates the
   digest and publishes again, with an event id that includes the digest. The pipeline writes a new evidence object (the evidence
   contract already says a changed label set makes a new object).

## Alternatives considered
- **Connectors also write a plaintext snapshot for the pipeline.** Simplest, and it is what the branch did. Rejected: it keeps a
  second, unencrypted copy of source data, which defeats the per-object key and the crypto-shred, and Object Lock on a plaintext
  copy would make the erasure impossible.
- **The pipeline holds the tenant KEK or calls KMS itself everywhere.** Rejected: every pipeline code path would need key access.
  One reader behind a port keeps that to one audited module.
- **A decrypt service over HTTP.** Reasonable later, once `services/gateway` exists. It changes where the reader runs, not the
  contract above, so it stays open.
- **Put the mapping in the pipeline.** Rejected: the pipeline would then know about the ingestion layer's event type and index.

## Consequences
- The pipeline needs `kms:Decrypt` (conditioned) and read access to the raw index. That widens the pipeline's blast radius; the
  conditions, the audit event and the separation from writers are what contain it.
- A shredded object cannot be re-processed. A replay of an old event for an erased object is skipped and audited, which is correct.
- Two small, add-only changes to `main`'s code: `source_url` on the envelope and event, and `publish_tombstone` and `acl_digest`.
  They touch `usep.ingestion`, which belongs to another team, so they need that team's review.
- Raw reads cost a KMS call per object. A short-lived in-memory cache of unwrapped keys per worker invocation is allowed; keys are
  never written to disk or logs.

## Open
- Who owns `RawReader`: the ingestion team (it knows the key scheme) or the pipeline team. Proposed: ingestion owns it, the pipeline
  imports only the port.
- Lease and cache lifetime of an unwrapped key (D5 says credentials are held only for their lease; the same should apply here).
- Whether `acl_digest` belongs on the index row or on a separate table (index schema is the ingestion team's).
- The raw-prefix IAM and KMS policy text; that is platform-iac work and is not written here.

## Implementation order
1. Add `source_url` to the envelope and `RawObjectPublished`; add `acl_digest` and the re-announce rule; add `publish_tombstone`.
2. `RawReader` and the `SnapshotReader` port, with tests over a fake key store, including tampering, a wrong tenant, a shredded
   object and a hash mismatch.
3. `S3RawEventPublisher` and the event mapping, with a contract test against the pipeline's `RAW_REQUIRED`.
4. Point the pipeline worker at `SnapshotReader` instead of the S3 snapshot store; keep the old store only for the demo.
5. Port the serverless entry points and un-skip their tests (`docs/review/lambda-path-port.md`).
