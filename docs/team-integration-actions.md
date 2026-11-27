# Action items for the other teams: connect to the ontology so the application works end to end

Status: proposal for the platform lead and each owner. Owners are the roles in `CODEOWNERS`. Everything below the line
"Built today" exists and is tested; every item under a team is **work for that team**, none of it is built.

## Built today (what the ontology side hands over)

| Interface | Where | What it gives |
|---|---|---|
| Loader | `usep.ontology.load_ontology(root, pins)`, `resolve_pins(root, ids)` | The one reader of the ontology. Fails closed, lists every problem. Returns concepts, relationships, vocabularies, mappings, policies, templates (core and pack), systems, glossary, precedence and a release digest. |
| Version pin | `bundle.release` (`core_version`, packs, `digest`) | What every event and package must carry so a run can finish under the version it started with. |
| Release event | topic `ontology.release` | Switches the pipeline among versions shipped in its package only. |
| Events out of the pipeline | topics `raw.*`, `entity.<domain>`, `evidence.<family>`, `quarantine` (schemas in `src/usep/pipeline/topics.py`) | Node and edge candidates, evidence pointers, quarantined records. |
| Evidence contract | `docs/contracts/evidence.md` | Redacted text, labels, ACL and egress decision per source record. |
| Graph stand-in | `usep.graph.entity_events.build_graph`, `GraphProjectionService`, `restrict_for_export`, Graphify adapter | A tenant graph from entity events, filtered before export. A stand-in for the resolver, not the resolver. |
| Ontology JSON | `usep.ontology.export.to_dto`, `ui/src/api/fixtures/ontology.json` | Definitions for the console. |
| Query templates | `ontology/templates/` (8 core) and `packs/<level>/<pack>/templates/` (pack, D2 awaiting acceptance) | Named Cypher with `{{access_predicate}}`, tenant filter, LIMIT, depth and fan-out caps. |
| Checks | `ontology/tools/check_ontology.py`, `evals/tools/check_golden.py` | Local stand-ins for pack CI and the golden-set gate. |

## The path every record must travel

```
sources -> C-01 connectors -> raw (S3) -> bus -> C-02 pipeline (G1) -> entity.* + evidence.*
   -> [resolver: 6] -> [validate/conflict: 7] -> [fabric writer + PostgreSQL commit: 9] -> [outbox: 10]
   -> [graph projector -> Neo4j] [vector projector -> pgvector] -> [context engine] -> [model gateway / harnesses / UI]
```
Everything in square brackets is missing. Until the first two exist, nothing downstream has trustworthy entity ids.

## Action items by team

### 1. Resolver and steward review (step 6): semantic architect, lead ontology engineer
This is the critical path. The pipeline publishes edges as `pending_resolution`, nodes without real ids.
- Read `entity.*` events; match each node to an existing entity by source identity, then approved aliases, then candidates.
- Assign the entity id (UUID v7). Replace `usep.labelling.labeller.derive_entity_id`, which is a stand-in.
- Resolve pending edge ends by (`source_system`, `source_id`, optional type). Same identity means resolve; different identity means a typed relationship (never merge).
- Thresholds from the diagram: auto-link at 0.92 or above, steward review from 0.75 to below 0.92, below that a new entity. Put them in config, not code.
- Steward queue for the middle band and for ends that match more than one node.
- Done when: replaying all `entity.*` events twice produces the same entities and edges, with zero `unresolved` ends in the sample data.

### 2. Fabric writer and PostgreSQL commit (steps 7, 8, 9): platform engineer, data owner
- Load the same ontology bundle (`load_ontology`) at the pinned version; reject any node or edge whose concept or relationship is not in it, or whose endpoints do not fit (`usep.ontology.view.OntologyView.endpoint_ok`).
- Apply the conflict rules: org pack `precedence.yml` decides which source wins per attribute. It is a placeholder until the week-4 workshop (ADR-17), so schedule the workshop first. Without a rule keep every claim and record the conflict; recency never decides.
- Enforce the constraints the shapes describe but the run-time cannot: exactly one owning Team per Service, cardinality, append-only assertions.
- Write current state, assertions, ownership, ACL, evidence refs and the outbox row in one transaction. Store `ontology.digest` with every assertion.
- Insert only through this writer (ADR-05). Dedupe on `idempotency_key`; deliver at least once.
- Done when: a commit is rejected for a bad concept, a second owning team, and a stale `source_version`; an accepted commit survives a replay unchanged.

### 3. Outbox relay and event bus (step 10, C-03): platform engineer
- Relay committed events to the consumers, at least once, idempotent.
- Add one SQS queue and one dead-letter queue per consumer on `entity.*` and `evidence.*` (ADR-19). The SAM template only covers `bus/raw.*` and is unvalidated: run `sam validate --lint` first.
- Register the new schemas in `usep.pipeline.topics.register_schemas`; bump versions, never change a topic's meaning.
- Done when: a failed consumer retries per message and lands in its dead-letter queue after the configured receives, with no other consumer affected.

### 4. Graph projector and Neo4j (C-04): graph engineer
- Replace the in-memory projection's input with committed state. Reuse `GraphProjectionService` for validation against the ontology; it already rejects unknown relationships, wrong endpoints and cross-tenant edges.
- Index on `tenant_id`, `entity_id`; keep edge properties `confidence_score`, `confidence`, `evidence_ref`, `valid_from`, `valid_to`, `source_system` (the templates read exactly these).
- Incremental upsert and retract; a full rebuild from committed state must give the same graph.
- Watermark and lag status per projection. A projector outage must retry or replay, never touch the commit.
- Done when: every core and pack template runs against the store with the access predicate supplied, and a rebuild equals the incremental graph.

### 5. Vector projector and embeddings (C-04): LLM and retrieval engineers
- Consume `evidence.<family>`; read the object at `evidence_ref`; chunk deterministically.
- Carry `sensitivity`, `acl`, `owners_only`, `tenant_id` and the ontology digest onto **every chunk**, and index them for filtering. Treat embeddings as restricted data (sensitivity 3, HLD 8).
- For one `(source_system, source_id)` keep only the newest `retrieved_at`, then highest `source_version`; a changed ACL writes a new evidence object, so older ones are stale.
- Call `usep.pipeline.egress.assert_allowed(evidence)` before text leaves the platform. Most records are blocked today because their ACL is unknown; plan for a local or hosted model for those.
- Once the resolver exists, store `entity_id` next to each chunk.
- Done when: a user without access to a record never receives its chunk, and an owners-only record is never embedded by an external service.

### 6. Context engine (C-05, L5): context-engineering lead
- Execute the named templates only (core and pinned packs'); never accept free Cypher. Supply `tenant_id` from the token and the access predicate from the policy decision point, **inside the match**, not as an output filter (ADR-06).
- Keep a table of runnable templates and a test that it equals the YAML set (core and pack). Today the guide says 3 of 8 core templates run; there is no code. Pack templates `app_references_of`, `app_documents_of` must be in it.
- Prune unseen paths during traversal and report cut points; do not reveal that something was withheld.
- Record the ontology digest in each context package and in its seal; a different pin must never reuse a cached package.
- Done when: the golden set (`evals/golden/`, 190 items) runs end to end and every permission-aware item returns nothing from `must_not_include`.

### 7. Model gateway and egress (C-09): security architect
- Enforce `egress.external_model` for every call; block on unknown ACL, sensitivity above 1, or redaction findings. Today nothing enforces it.
- Log each decision to audit. Provide an approved route (local model) for records the default policy blocks.
- Decide D8 (egress defaults) and ACL harvest for ServiceNow, ADO work items and Figma, which stay owners-only today.
- Done when: a record with an unknown ACL cannot reach an external model by any path, proven by a test.

### 8. Harness runtime and action adapters: harness engineer
- Read criticality, regulatory scope and sensitivity (the policy hooks) from entities; apply core policies (`deny_by_default`, `unknown_acl_owner_only`, `tier3_never_autonomous`, `decision_critical_conflict_blocks_commit`, `restricted_personal_data_excluded`) and pack policies, which can only deny, require approval or restrict to owners.
- Only action adapters write to sources (ADR-05). Approval tier comes from the org pack's approval matrix (placeholder today).
- Done when: a tier_1 change cannot run without Tier 2 approval, and a pack cannot grant anything the core denies.

### 9. Audit (services/audit): governance lead
- Record, for each ingest, commit, query and egress decision: tenant, actor, ontology digest, evidence refs, decision and reason. Audit is a control, append-only.
- The pipeline already writes quarantine records and evidence; add consumers for them.
- Done when: any answer can be traced to its evidence and the ontology version that produced it.

### 10. Evaluation (services/evaluation): context-engineering lead
- Replace the synthetic golden set with SME-reviewed items from pilot data (OI-49). Do not publish scores from the synthetic file.
- Run the golden set per template and difficulty; add the edge-precision check (`scripts/edge_precision.py`, about 100 labelled edges per relation type) as a gate.
- Done when: recall at 8 and evidence support are measured on reviewed items, per template.

### 11. API and console (UI, gateway): UI team and API team
- Serve `GET /api/configurations/{id}/ontology` (shape in `docs/ui-ontology-view-brief.md`) from `usep.ontology.export.to_dto`, scoped to the tenant's pinned packs.
- Serve the graph endpoint from the graph store, filtered by tenant and permission before it returns anything; never send `owners_only` nodes the caller may not read. Until then use `restrict_for_export`.
- Real login (OIDC/SSO), tenant isolation and URL validation belong to the API, not the UI.
- Done when: two tenants with different pins see different ontologies and graphs, and neither can fetch the other's by id.

### 12. Ontology registry and pack CI (C-06, C-07): platform lead, lead ontology engineer
- Pack CI: run `check_ontology.py` and `check_golden.py` on every pull request; add signing; publish signed versions. Packs are unsigned today (`signed: false`).
- Registry: hold signed packs and tenant pins; serve pins to the pipeline, resolver, writer and engine. Replace the `ontology.packs` config key.
- Distribute versions by `ontology.release` events, and let a consumer load a version that is not shipped inside its package (today it refuses).
- Done when: publishing a pack version changes behaviour in every service without a code release, and an unsigned or unpinned pack is refused.

### 13. Connector owners (C-01): connector developers
- Harvest source permissions the ontology uses for labelling: Jira project roles, ServiceNow ACLs, ADO work-item project visibility and area permissions, Figma file access. Until then those records are owners-only.
- Propagate deletions and permission removals; today a removed object's evidence stays.
- Keep the source-id formats agreed in D5; they are the resolver's identity keys.
- Done when: a permission change at the source changes `acl_state` and the evidence label hash within one sync.

### 14. Platform and IaC (platform-iac): platform lead
- Validate and deploy the SAM stack per environment; KMS key policy, bucket Object Lock on `evidence/`, lifecycle and replication are open (ADR-19).
- Provision PostgreSQL, Neo4j, pgvector, the outbox relay and the per-consumer queues; secrets from the secrets manager, never from Git.
- Done when: `dev` runs the full path on synthetic data with no manual steps.

### 15. Ontology owners and ARB: lead ontology engineer, enterprise architect, security architect
These decisions block items above. Source: `docs/review/ontology-owner-review.md` and `docs/review/ontology-gaps-decision-brief.md`.
- D2 accept pack-level templates (built, awaiting acceptance); unblocks items 4 and 6 for `references` and `documents`.
- OI-59 `modifies` (Change to Service), plus Sprint, File, `CHILD_OF`, KPI; unblocks impact-analysis questions.
- ADR-17 precedence workshop (week 4); unblocks item 2.
- D3 and the identity aliases decision; unblocks person-centred questions.
- D5 source-id formats; unblocks item 1. D8 egress defaults; unblocks item 7.
- Replace placeholder packs with real regulatory and organisation content; name the owners.

## Suggested order
1. **Now, in parallel:** items 12 (CI and registry design), 14 (validate the stack), 13 (permission harvest), and the ARB decisions in item 15. None depends on another team's code.
2. **Next:** item 1 (resolver), then item 2 (fabric writer and PostgreSQL), then item 3 (outbox and queues).
3. **Then, in parallel:** items 4 and 5 (projectors), then item 6 (context engine).
4. **Last:** items 7, 8, 9 (gateway, harness, audit) wired in as each stage appears, and 10 and 11 to measure and show it.

First end-to-end milestone: one Jira issue and one merge request that cites it, from connector to a context package answering "which merge request references this issue", with its evidence, under a pinned ontology digest, for a user allowed to see it and not for one who is not.

## What the ontology team still owes the others
- Keep the three contracts stable (evidence, entity events, ontology JSON); any change bumps a version and updates the tests that pin them.
- Review requests for new concepts or relationships; each needs core files, shapes, the check's concept sets and golden items together.
- Answer "which concept does this map to" for new sources through application-pack mappings.
