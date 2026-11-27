# Production readiness checklist

Status: living document. Update a row when its evidence exists, not when work starts.
Owners are **roles** from `CODEOWNERS` (HLD 4.4 and 12.1), not people; map them to names when O-08 is answered.
Decisions that are not ours to make are in `docs/claude-project/knowledge/07-open-items.md` (O-nn); rows link to them instead of copying them.

**Status:** `Not started` · `In progress` · `Blocked` (needs a decision or another row) · `Done` (evidence exists).
**Size:** S is days, M is a few weeks, L is longer. Rough, to order the work, not to promise dates.
**Done when** says what proves a row is finished: a passing test, an accepted ADR, a run in staging. "Written" is not done.

## What is true today (2026-11-27)
- Built and tested: ontology (pack CI, loader, gate G1, registry with signing, Graphify graph), pipeline C-02, fabric writer C-04 on PostgreSQL, the console UI, and the console API with the ontology and a per-configuration check.
- Never run: the IaC (`platform-iac/`), the release workflow (`.github/workflows/ontology-ci.yml`), any connector against a real source, the pipeline on real data.
- Stand-ins: the console's graph is a provisional rule-based builder, not the pipeline; the ontology is placeholder reference packs, unsigned; the agent is rule-based; sign-in is one admin password.
- Parked: the serverless connector path (`docs/review/lambda-path-port.md`, 6 test modules skipped).
- Repo: ADR-19 (event bus), ADR-19 (Graphify), ADR-20, ADR-21 and ADR-24 are all `Proposed`.

## A. Before any real data touches it
| ID | Item | Owner role | Depends on | Size | Status | Done when | Links |
|---|---|---|---|---|---|---|---|
| A1 | Real sign-in (OIDC/SSO), roles, sessions that survive restarts and scale out; tenant id in every token | Platform lead, security architect | O-08 | M | Not started | Login through the identity provider; two tenants cannot see each other's configurations (test) | `services/connectors/console_api/auth.py` |
| A2 | Keys and credentials in KMS or Vault, no `DEV_KEK_B64`, no secrets in `.env` | Security architect, platform lead | O-04, O-18, ADR-22 | M | Blocked | Staging runs with no dev key; the service refuses to start with one outside dev | O-04, O-18 |
| A3 | ADR-22 (Vault and SPIFFE) written and ratified. Code already cites it; no file exists | Security architect | | S | Not started | ADR-22 in `docs/adr/`, status Accepted | `src/usep/adapters/vault/resolver.py` |
| A4 | Pipeline can read `main`'s encrypted raw objects (raw reader, separated roles, audited decrypts) | Security architect, platform lead | ADR-24 accepted, A2 | M | Blocked | Tests for tampering, wrong tenant, shredded object, hash mismatch; roles in IaC | ADR-24 |
| A5 | Each connector run against a real source: Jira, GitLab, GitHub, ServiceNow, Confluence (Figma and Azure DevOps after the DPIA). Rate limits, permissions, large backfill | Platform lead | A2 | M–L | Not started | One real run per connector in staging, with a recorded result | O-05 |
| A6 | Permissions harvested for the sources still `unknown` (Jira project roles, ServiceNow ACLs, Azure DevOps areas) | Governance lead, platform lead | A5 | M | Not started | `acl_state` is `known` for those sources, or the owners accept owners-only | `docs/contracts/evidence.md` |
| A7 | Sensitive-data filter pattern list reviewed by security | Security architect | | S | Not started | List reviewed and recorded | O-11 |
| A8 | Real ontology packs from the owners, a production signing key, `allow_reference_packs=false` | Lead ontology engineer, enterprise and application architects, governance lead | O-15, O-21, O-22 | M | Blocked | Packs signed and pinned; `config/registry/trusted_keys.yaml` filled; placeholder banner gone | ADR-20 |
| A9 | Deploy the IaC to staging: cfn-lint, security review, registry bucket with Object Lock, KMS key, roles | Platform lead, security architect | A2 | M | In progress (written, never run) | Stack deployed in staging; `tests/registry/test_registry_iac.py` plus a real deploy | `platform-iac/registry/template.yaml` |
| A10 | Run the release workflow once end to end (tag, two reviewers, publish) | Platform lead, lead ontology engineer | A8, A9 | S | Not started | A signed release published from CI | `.github/workflows/ontology-ci.yml` |

## B. Turn the demo path into the real data path
| ID | Item | Owner role | Depends on | Size | Status | Done when | Links |
|---|---|---|---|---|---|---|---|
| B1 | Connector output reaches the pipeline (ADR-24 steps 1 to 4: `source_url`, ACL digest, tombstone event, `S3RawEventPublisher`) | Platform lead | A4 | M | Blocked | Contract test against the pipeline's `RAW_REQUIRED`; a deleted object retracts its entity end to end | ADR-24 |
| B2 | Deletion propagation, backfill cap, full refresh, webhooks, Lambda entry ported onto `main`'s ingestion layer; skipped tests un-skipped | Platform lead | B1 | M | Blocked | The 6 skipped modules pass | `docs/review/lambda-path-port.md` |
| B3 | Pipeline output committed by the fabric writer into PostgreSQL (needs RDS, roles, migrations run) | Platform lead | A9, B1 | M | In progress (code and tests exist; never run on real events) | Real events committed; outbox lag and dead rows observable | ADR-21 |
| B4 | Console `GET /graph` reads committed state, not the provisional builder; configurations stored in PostgreSQL, not local JSON files | Platform lead | B3 | M | Not started | Console graph equals the committed graph; restart loses nothing | `services/connectors/console_api/store.py` |
| B5 | Console loads the ontology from the signed registry, checking signatures and pins | Lead ontology engineer | A8, A10 | S | Not started | Console refuses an unsigned or altered ontology | ADR-20 |
| B6 | Entity and link resolver (alias, steward and threshold policy first) | Lead ontology engineer, governance lead | O-15 | L | Blocked | Policy brief answered; resolver built; ~100 edges per relation hand-checked (`scripts/edge_precision.py`) | `config/runtime/resolution.yaml` |
| B7 | Graph projector (Neo4j) and vector projector (pgvector) | Platform lead | B3, B6, O-10 | L | Not started | Rebuild from committed state; ACL and tenant filtered inside the query | O-10 |
| B8 | A Change-to-Service relationship (`modifies`) decided: add it to the core or leave it out | Lead ontology engineer, ARB | | S | Not started | Decision recorded; demo and builder agree with the ontology | `docs/review/ontology-owner-review.md` |

## C. Operations
| ID | Item | Owner role | Depends on | Size | Status | Done when | Links |
|---|---|---|---|---|---|---|---|
| C1 | One CI pipeline running every suite on every PR; branch protection with CODEOWNERS review | Platform lead | | S | Not started | A red test blocks a merge; the six commands in `CLAUDE.md` run in CI | `CLAUDE.md` |
| C2 | Observability: outbox lag, dead rows, failed runs, KMS errors; dashboards and alarms | Platform lead | B3 | M | Not started | Alarm fires in a drill | O-20 |
| C3 | Backups and restore tested for PostgreSQL and the registry; runbook | Platform lead | A9 | M | Not started | A restore is timed and recorded | `platform-iac/runbooks/` |
| C4 | Failure drills: bus down, KMS denied, poison event, relay crash | Platform lead | B3 | M | Not started | Each drill recorded with the result | ADR-21 |
| C5 | Load tests: large backfill, relay throughput, connection pooling (RDS Proxy); more than one relay worker | Platform lead | B3 | M | Not started | Numbers recorded against targets | ADR-21 |
| C6 | Audit location, retention (7-year WORM) and compliance sign-off | Governance lead | | M | Blocked | Decisions recorded as ADRs | O-09, O-12 |
| C7 | DPIA for Figma and Azure DevOps | Governance lead, sponsor | | S | Blocked | Sign-off date recorded | O-05 |
| C8 | Security review and penetration test | Security architect | A1, A2, A4 | M | Not started | Findings closed or accepted | |
| C9 | Named owners for every role in `CODEOWNERS` | Sponsor | | S | Blocked | `CODEOWNERS` has team handles | O-08 |

## D. Product and UX
| ID | Item | Owner role | Depends on | Size | Status | Done when | Links |
|---|---|---|---|---|---|---|---|
| D1 | Tenant custom-label definitions served by an API and shown on the Ontology page | Lead ontology engineer | B3 | M | Not started | Page lists real custom labels | `usep.labelling` |
| D2 | A language-model agent behind the model gateway and egress checks (the ontology holds no tenant data, so it is the safer first source) | Context engineering lead, AI platform lead | O-02, O-16 | L | Blocked | Gateway exists; egress enforced; golden set scored by SMEs | O-02, O-07, O-16 |
| D3 | Responsive layout (the shell has a fixed sidebar and no width breakpoints), accessibility review | Application architect (UI) | | M | Not started | Usable at tablet width; audit findings closed | `ui/src/styles/layout.css` |
| D4 | Browser tests for the console flow in CI | Platform lead | C1 | M | Not started | Sign-in to ontology to agent flow runs in CI | |
| D5 | SME-graded golden items per domain before any accuracy claim | Context engineering lead | | L | Blocked | 150 graded items per domain | O-07 |

## E. Step 1 packet: decisions to take to ARB and the security architect
Five ADRs are `Proposed`. Each needs the decision below before the rows it blocks can start.

| ADR | Decides | Who accepts | Question to put | Blocks |
|---|---|---|---|---|
| ADR-19 (event bus) | S3 holds events, SQS delivers, instead of Kafka | ARB | Is S3 plus SQS acceptable given HLD 16 Table 34 names Kafka? What is the latency and rate ceiling? | B1, B3 |
| ADR-19 (Graphify) | Graphify as a representation and query layer only, not the graph store | ARB, legal | Licence (sources disagree: Apache-2.0, MIT or both). The decisions register says the graph store is Neo4j; confirm Graphify stays export-only | B7 |
| ADR-20 | Signed immutable ontology releases, KMS key, trust store, per-tenant pins | Security architect, platform lead, semantic architect | Key custody and rotation (manual); Object Lock governance versus compliance mode; one signature or two | A8, A9, A10, B5 |
| ADR-21 | PostgreSQL commit point, RLS, transactional outbox, one writer per event | ARB | Single relay worker acceptable for the pilot? Identity rule until the resolver exists | B3, B4 |
| ADR-24 | Who may decrypt raw data; event mapping; tombstone event; ACL digest | Security architect; ingestion team reviews | Which role decrypts, and with what KMS conditions? Accept the add-only fields in `usep.ingestion`? | A4, B1, B2 |
| ADR-22 (missing) | Vault and SPIFFE for secrets | Security architect | Write it: the code cites it but no file exists | A2, A3 |

Ask for each decision in one meeting if possible; A2, A3 and A4 share the same reviewer.

## How to keep this honest
- Change `Status` only with the evidence in `Done when`. A written template, a passing unit test on a fake, or a demo run is `In progress`.
- When a row needs a decision, set `Blocked`, link the O-nn or ADR, and name the owner role who answers.
- Remove a row only when an ADR or a run records its result.
