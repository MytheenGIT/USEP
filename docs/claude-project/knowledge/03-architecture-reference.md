# Architecture reference (PoC)

This summarises the USEP HLD v1.0, LLD v0.1 and the repository README for day-to-day work. When this summary and the HLD or LLD disagree, the HLD or LLD governs, and the conflict is logged in the open items.

## 1. What the PoC does

The PoC reads Jira stories (by JQL), GitLab repositories (merge requests, commits, diffs), Confluence pages and ADRs, and later Figma and Azure DevOps. It stores raw source JSON as evidence, normalises and chunks it, embeds the chunks, and writes facts to Postgres. A projection in Neo4j is built from those facts. Users ask questions in a UI. The Ask tab builds a sealed context package, runs hybrid retrieval (vector plus full-text, merged by reciprocal rank fusion), and returns an answer with citations. Every step is audited.

## 2. The eight PoC modules and where they live

| Module | What it does | Repository location | Sprint in the plan |
|---|---|---|---|
| 1. UI and configuration | Admin login, source configuration (GitLab, Jira, Confluence, Azure DevOps, Figma, S3), delivery metrics, knowledge graph, ontology, token consumption | `services/gateway/` (API). Web app folder not yet created (gap). | 5 (gateway) |
| 2. Ingestion | REST pull with a default 6-month window (user-configurable); raw JSON to S3 evidence | `services/connectors/git`, `jira`, `confluence`; Figma and S3 folders not yet created | 3 |
| 3. Processing | Normalise, chunk, embed into pgvector; metadata in Postgres | `services/pipeline/`, `services/fabric-writer/`, `services/projectors/` | 3 |
| 4. Retrieval | Hybrid RAG with access predicate and tenant ID | `services/context-engine/` | 4 |
| 5. LLM gateway | Frontier models through configuration (Bedrock first); token monitoring; sensitive-data filter | `services/model-gateway-config/`. Sensitive-data filter has no folder yet (gap). | 4 |
| 6. Ontology and knowledge graph | Core and packs; graph projection | `ontology/`, `services/ontology-registry/`, `services/projectors/` | 2 (ontology) |
| 7. Observability, evaluation and audit | Audit log, OpenTelemetry, golden set runs | `services/audit/`, `services/evaluation/`, `observability/` | 6 |
| 8. Infrastructure and delivery | Terraform, CI/CD, stores, bus, Compose for PoC | `platform-iac/` | 1 |

Building modules 1 to 7 now runs ahead of the sprint plan. Label PoC output as PoC, not as a sprint deliverable.

## 3. Components (HLD inventory)

| ID | Component | Notes |
|---|---|---|
| C-01 | Connectors (Git, Jira, Confluence, Figma, Azure DevOps) | Write raw events to Kafka and evidence to S3. Never write facts directly. |
| C-02 | Pipeline (normalise, chunk, embed) | Python |
| C-03 | Event bus | Kafka with schema registry (ADR-020) |
| C-04 | Fabric writer and projectors | The only fact-insert path (ADR-05) |
| C-05 | Stores | Postgres with pgvector (commit point), Neo4j Community (PoC projection), S3 with Object Lock (evidence) |
| C-06 | Ontology registry | Not yet built |
| C-07 | Pack CI | Checks ontology packs on pull request |
| C-08 | Context engine (retrieval) | Sprint 4 |
| C-09 | Model gateway configuration | Bedrock first (ADR-022) |
| C-10 | Harness runtime | Sprint 5. PoC Ask tab is a Tier 0 sealed-package harness (ADR-027). |
| C-11 | Action adapters | Sprint 5. Not enabled in the PoC. |
| C-12 | API gateway and MCP server | Sprint 5 |
| C-14 | Identity | Single admin for PoC (ADR-026); OIDC before pilot |
| C-15 | Evaluation | Sprint 6. Golden set in `evals/`. |
| C-16 | Audit | Sprint 6. Hash-chained, append-only. |
| C-17 | Observability | OpenTelemetry Collector; Grafana for PoC; portable to Datadog and Dynatrace |

## 4. Stores and retention

| Store | Holds | Retention (HLD Table 9 unless noted) |
|---|---|---|
| Postgres with pgvector | Facts, chunks, embeddings, metadata, audit events | Facts while the source exists; embeddings deleted with their source |
| Neo4j Community (PoC) | Rebuildable graph projection | Rebuilt from Postgres; no independent retention |
| S3 with Object Lock (compliance) | Raw evidence snapshots, prompts and completions by reference | While the source entity exists, plus 1 year. Crypto-shredded on erasure (ADR-033). |
| Audit log | Hash-chained events | PoC: 6 months (ADR-032). Pilot: 7 years WORM. |
| Kafka | Events, with per-key ordering | Entity topics 7 days; raw topics 30 days (LLD 2.8) |

Erasure follows the HLD rules: tombstones, deletion propagated within 24 hours, erasure complete within 7 days.

## 5. Main flows

Ingestion: a connector pulls changes from a source (incremental, with a sync cursor and an overlap window), writes the raw payload to S3 and an event to `raw.<family>`. The pipeline normalises and chunks it, and quarantines anything that fails a check to `quarantine.<family>`. Embeddings are created in-network. The fabric writer commits facts to Postgres, and projectors update Neo4j and advance `projection.watermark`.

Answer: the Ask tab receives a question, derives intent, and builds a sealed, signed context package from retrieval results (access predicate applied inside retrieval). The package must pass its gates: schema, freshness, privacy, coverage and injection. The LLM gateway calls the model through Bedrock after the sensitive-data filter. The grounding gate checks the answer against the package: commit at 0.98 or above, advisory at 0.85 or above. Citations are validated. Every step writes an audit event.

Reconciliation: a daily job compares source and store and reports missing, extra and stale items.

## 6. Autonomy

Tier 0 is read-only. Tiers 1 to 3 add actions, with Tier 3 never autonomous. The PoC is Tier 0 only.

## 7. Deployment

PoC: Docker Compose on one AWS host, with the same images and configuration the Kubernetes target uses (ADR-031). Target: managed Kubernetes on EKS, with Terraform, Argo CD and signed images with SBOMs (HLD 10). The `platform-iac/` folder is an empty skeleton until Sprint 1.

## 8. Key constraints in one place

Tenant ID everywhere. Authorization inside retrieval. Only the fabric writer inserts facts. Only action adapters write to sources. Audit before action. Fail closed. No secrets in Git. Embeddings are restricted data. Prompts are stored by reference. Retrieval scores are relevance, not truth.
