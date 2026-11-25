# Decisions register (PoC)

Status as of 25 Nov 2026. Each decision is recorded as an ADR in `docs/adr/`. Statuses are drafts until the ARB and named owners approve them. Where this register and the PoC spec v0.3 disagree, this register wins.

## Recorded decisions

| ID | Decision | ADR | Type | Exit or follow-up |
|---|---|---|---|---|
| D1 | Neo4j Community for the PoC graph projection. Tenant isolation is enforced by an application-level predicate on `tenant_id`. | ADR-019 | Deviation from HLD Table 28 | Enterprise licence before any multi-tenant pilot. Licence owner to be named. |
| D2 | Apache Kafka with schema registry from Sprint 1. Topics: `raw.<family>`, `entity.<domain>`, `quarantine.<family>`, `projection.watermark`, `governance.verdict`, `governance.deletion`. | ADR-020 | Accepted | None. Sprint sequencing changes. |
| D3 | AWS is the cloud provider for PoC and pilot. | ADR-021 | Accepted | Customer confirmation of AWS and data residency. |
| D4 | Amazon Bedrock is the LLM gateway. Other providers are configuration. The sensitive-data filter and token monitoring sit in front of every call. | ADR-022 | Accepted with conditions | Approved Bedrock endpoints per data class (open item O-02). |
| D5 | Evidence snapshots in S3 with Object Lock, compliance mode. Kept while the source entity exists, plus 1 year. | ADR-023 | Accepted | Four snapshot points to settle before the first connector writes data (O-01). |
| D6 | In-network open-source embedding model. Not Voyage AI for restricted data. Embeddings are restricted and are deleted with their source entity. | ADR-024 | Proposed | Model name needed before Sprint 4 (O-03). |
| D7 | Figma and Azure DevOps stay in PoC scope after a DPIA. No live connection before the DPIA is signed. | ADR-025 | Accepted with conditions | DPIA owner and sign-off date (O-05). |
| D8 | Single local admin account for the PoC. Session lifetime 8 hours. | ADR-026 | Deviation from HLD 7.2 | OIDC and MFA before any pilot user. |
| D9 | The Ask tab builds a sealed, signed context package and passes the package and grounding gates from the start. | ADR-027 | Accepted | None. |
| D10 | Full prompt text is stored in the evidence store with a hash. Logs carry the ID only. | ADR-028 | Accepted | Governance sign-off on prompts that may carry restricted content (O-06). |
| D11 | Claude model chosen by an evaluation run on the golden set through Bedrock, not up front. | ADR-029 | Accepted | Depends on O-02. Record cost per run and token budget in a follow-up ADR. |
| D12 | Access predicate is present in every retrieval query, vector and full-text, with `tenant_id`. For the PoC the predicate's value is the admin scope. | ADR-030 | Deviation from ADR-06 | Per-user ACL mirroring before any second user. |
| D13 | Docker Compose on one AWS host for the PoC. Same images and config as the Kubernetes target. | ADR-031 | Deviation from HLD 10 | Same artefacts deployed to EKS before pilot. |
| D14 | Audit records: 6 months for the PoC. 7 years WORM from pilot. | ADR-032 | Deviation from HLD Table 9 and LLD 2.8 | Exit date and compliance sign-off before pilot. Two audit locations (O-09). |
| D15 | Erasure by crypto-shredding: a per-object data key, destroyed on erasure. Redaction before write. | ADR-033 | Accepted with conditions | Key-management design and its ADR (O-04). |
| D16 | KPI, Change-to-Service and review-event concepts go in a PoC pack first, then to core through the change path. | ADR-034 | Accepted | ARB approval for promotion to core. |
| D17 | PoC golden set is engineering-graded. Results are not pilot accuracy evidence. | ADR-035 | Accepted | 150 SME-graded items per domain before any accuracy claim (O-07). |

## Superseded from the PoC spec v0.3

| Spec v0.3 said | Now | Why |
|---|---|---|
| Voyage AI as default embedding | In-network open-source model (D6) | HLD 7.2 treats embeddings as restricted |
| Procrastinate queue on Postgres | Kafka (D2) | HLD C-03 default; LLD 3.5 ordering and replay |
| Edges kept in Postgres tables, no graph store | Neo4j projection; Postgres stays the commit point (D1) | ADR-03; LLD 3.3 |
| Raw JSON expires after 30 days | Evidence snapshots with Object Lock (D5) | HLD 4.6 |
| 6-month audit default, configurable | 6 months for PoC only (D14); 7 years WORM from pilot | HLD Table 9 |
| Docker Compose only, no target | Compose for PoC (D13); EKS before pilot | HLD 10 |
| Basic login as the model | Single admin for PoC (D8); OIDC before pilot | HLD 7.2 |
| `prompt_store` table | Evidence store, referenced by ID (D10) | HLD 7.2 |
| Credentials envelope-encrypted with master key from env | Vault holds the master key; Postgres holds encrypted credentials | Repo rule: Vault references. ADR not yet written (see pending ADRs). |
| Six modules, module 6 is observability | Eight modules, as listed by the user on 25 Nov 2026 (see architecture reference) | Scope change |
| Our own ontology concepts (WorkItem, Change, Document, and so on) | USEP core concepts, sources mapped through the app pack | Guide, ADR-034 for metrics |

## Still to decide (no ADR yet)

Credentials and Vault (proposed ADR-036). The event-bus port, so pipeline code does not depend on Kafka directly (proposed ADR-037). Observability: Grafana with OpenTelemetry, portable to Datadog and Dynatrace (C-17). This is accepted in the spec, and its ADR still has to be written. Sensitive-data filter pattern list, which needs security review. Single-region audit versus the two-location rule (ADR-032 and O-09).
