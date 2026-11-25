# Open items

Each item names the decision, the owner role and the date it is needed by. Remove an item only when an ADR records its answer. Update the list when a decision is made.

| ID | Open item | Owner role | Needed by |
|---|---|---|---|
| O-01 | Evidence snapshot points: when the snapshot is written, whether redaction runs before the write, whether unchanged content is skipped, and whether every version is kept | Governance lead with platform lead | Before the first connector writes data (Sprint 3) |
| O-02 | Approved Bedrock model endpoints per data class, and the same-class fallback | AI platform lead | Week 3 (Appendix A); before any model call with restricted data |
| O-03 | Name of the in-network open-source embedding model | AI platform lead | Before Sprint 4 (index sizing) |
| O-04 | Key-management design for crypto-shredding (Vault or AWS KMS) and its ADR | Security architect with platform lead | Before the first evidence object is written |
| O-05 | DPIA for Figma and Azure DevOps, with sign-off date | Governance lead and sponsor | Before either connector connects to live data |
| O-06 | Governance sign-off that prompts, which may carry restricted content, can be stored in the evidence store | Governance lead | Before prompts are stored |
| O-07 | Named SMEs per domain and 150 SME-graded golden items per domain | Context engineering lead with sponsor | Before any accuracy claim |
| O-08 | Named owners for all roles in CODEOWNERS | Sponsor | Week 1 |
| O-09 | Audit location: two locations (HLD, ADR-13) versus single region for the PoC, and whether a backup region is acceptable | Platform lead with governance lead | Before Sprint 6 and before pilot |
| O-10 | Enterprise licence for Neo4j, and the licence owner (ADR-019 exit) | Platform lead | Before any multi-tenant pilot |
| O-11 | Sensitive-data filter pattern list, reviewed by security | Security architect | Before the filter runs on real data |
| O-12 | Audit retention exit to 7 years WORM, with compliance sign-off (ADR-032) | Governance lead | Before pilot |
| O-13 | Human-in-the-loop metric concepts (KPI, Change-to-Service, review events) and their promotion to core (ADR-034) | Lead ontology engineer; ARB | Before the metrics module is built |
| O-14 | Whether the HLD and LLD are binding, their status, and their document dates. Both leave "Prepared by" and "Audience" blank. | Sponsor and semantic architect | Week 1 |
| O-15 | Source precedence and conflict rules (ADR-17, still Proposed; workshop in week 4) | Semantic architect | Week 4; blocks any precedence logic |
| O-16 | Chosen Claude model after the evaluation run (ADR-029) | Context engineering lead | After O-02 |
| O-17 | Confirmed framework set against HLD 16 Table 34 (SQLAlchemy, Alembic, psycopg, Procrastinate status, and others) | Platform lead | Sprint 1 |
| O-18 | Credentials design: Vault holds the master key; Postgres holds encrypted credentials (ADR-036, not yet written) | Security architect | Sprint 1 |
| O-19 | Event-bus port so pipeline code does not depend directly on Kafka (ADR-037, not yet written) | Platform lead | Sprint 1 |
| O-20 | Observability ADR: Grafana with OpenTelemetry, portable to Datadog and Dynatrace (C-17) | Platform lead | Sprint 1 |
| O-21 | Azure DevOps mapping in the app pack | Application architect | Before Azure DevOps connector |
| O-22 | Project-level pack for the state translation that is not yet built | Delivery lead | Sprint 2 |

The PoC spec items O-01 to O-22 supersede earlier numbering in the spec v0.3 (which listed open embedding, Figma scope, SSO provider and retention questions). Those are covered here by O-02, O-03, O-05, O-11 and O-12.
