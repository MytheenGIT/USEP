# USEP: the product repository skeleton

Layout from RM 11.1. This is one Git repository. It holds definitions only: code, infrastructure code, ontology, harnesses, policies, evaluation assets and ADRs. Runtime data (the four stores, evidence, events), secrets, keys and run state are never committed; `.gitignore` blocks them. Plans, status and evidence go in `../phases/`; reference goes in `../knowledge/`.

Current content: the repository setup (`.gitignore`, `.gitattributes`, `.editorconfig`, `.env.example`, `CODEOWNERS`, `requirements-dev.txt`), the ontology in `ontology/` (see `ontology/README.md`), a draft golden set with its checker in `evals/` (see `evals/README.md`), and the first ingestion slice: source connectors as Lambdas (`services/connectors/`), the acquisition pipeline and ontology run-time (`src/usep/`), and a deployment template (`platform-iac/lambda/`). See "Ingestion flow" below. Empty folders carry a `.gitkeep`. Everything else is an empty skeleton until its sprint starts.

Status: the ingestion slice (connectors, S3 event bus, acquisition pipeline, ontology run-time) works end to end on dummy data and is not deployed or run against real systems. Nothing after the entity candidates exists yet (resolver, fabric writer, stores, projectors). The proposals (ontology attributes, golden set entities, freshness and fetch design) are pending ARB or SME review (OI-49 and the open ADRs in `../knowledge/08-conflicts-and-open-items.md`). Nothing here is signed or published.

## Git setup

- Default branch `main`. Protect it; merge by pull request only, with CODEOWNERS review (HLD 6.2 change path for `ontology/`).
- Line endings are LF (`.gitattributes`), so signed packs and canonical hashes are stable across machines.
- Never commit: `.env` files, keys, certificates, `*.tfstate`, database dumps, event-bus objects, graph data, evidence or sealed-package exports, model weights, Office or PDF files. Use Vault references.
- `CODEOWNERS` lists roles, not people. Replace each role with a team handle when the owners are named.
- Run the checks before every push (see "Run and test" below).
- Before sharing the folder with the team, check `git status --ignored` so no local, secret or runtime file goes out. Share through Git, not a zip copy.

| Folder | Holds | First sprint | Owner role (HLD 4.4, 12.1) |
|---|---|---|---|
| `platform-iac/` | Terraform modules, cluster add-ons, Argo CD apps for dev, test, staging, prod; runbooks | 1 | Platform lead |
| `services/` | One folder per service (see below) | 1 to 6 | Per component |
| `ontology/` | Core, packs (industry, org, app, project), shapes, templates, tests | 2 | Lead ontology engineer |
| `harnesses/` | `architecture-impact/`, `development/`: definition, verifiers, tests | 5 | Harness engineer |
| `policies/` | Rego bundles and policy tests | 1 | Security architect |
| `evals/` | Golden set per domain (engineering draft: 182 items, synthetic, OI-49), its checker and tests; regression and red-team suites | Draft now; suites in 4 | Context engineering lead |
| `docs/adr/` | ADR-19 onward (ADR-01 to ADR-18 are in HLD 18) | any | Semantic architect |

## Service folders (under `services/`)

| Folder | Component | Sprint | Language default (HLD 16) |
|---|---|---|---|
| `gateway/` | C-12 API gateway | 5 | Python 3.12, FastAPI |
| `connectors/git`, `connectors/jira`, `connectors/confluence` | C-01 | 3 | Python; Go or Java 21 allowed |
| `pipeline/` | C-02 | 3 | Python |
| `fabric-writer/`, `projectors/` | C-04 | 3 | Python |
| `context-engine/` | C-08 | 4 | Python |
| `model-gateway-config/` | C-09 | 4 | Configuration for an open-source LLM gateway |
| `harness-runtime/` | C-10 | 5 | Python; Temporal workers |
| `action-adapters/` | C-11 | 5 | Python |
| `mcp-server/` | C-12 MCP | 5 | Python |
| `evaluation/` | C-15 | 6 | Python |
| `audit/` | C-16 | 6 | Python |

Stores (C-05), bus (C-03) and identity (C-14) are provisioned from `platform-iac/`; observability (C-17) config sits there too.

## Rules for anything created here

- Keep code technology-agnostic: `domain/` and `ports/` import no vendor SDK; vendors live in `adapters/<tech>/`; connections are config keys plus Vault references (`../config/connections.yaml`, `../knowledge/10-agnostic-code-and-connections.md`).
- Name keys lower_snake_case with a service prefix; use the catalogue in `../config/defaults.yaml`.
- Generated IDs are UUID v7; timestamps UTC ISO 8601 with milliseconds; watermarks are event times.
- Only the fabric writer inserts into fact tables; only action adapters write to sources (ADR-05); nothing writes directly to a projection store.
- Tenant ID is in every token and every query. Authorization is inside retrieval, not after it.
- No secrets in code, images, prompts, logs or Git. Use Vault references.
- Every story cites component, source section, ADR and test (`../templates/story.md`). Every piece of delivered work gets a build record.
- Technology choices follow the reference profile (HLD 16, Table 34), and each one is swappable only by ADR. Python 3.12 and FastAPI are the default for every service. Any other language for a service (for example Go or Java 21 for a connector) needs its own ADR. Do not add a vendor (for example LangGraph, Graphify or JEV) until its ADR is accepted.

---

# Ingestion flow (C-01, C-03, C-02)

S3 holds the events and SQS delivers them (ADR-19, proposed). No Kafka. One stack per environment (`dev`, `staging`, `prod`).

```
EventBridge schedule {"source": "jira"}
   v
[1] Connector Lambda  usep-<env>-connectors   (services/connectors/lambda_handler.py)
    read cursor -> fetch from the source API (incremental)
    per object: raw snapshot -> S3 raw/...   then event -> S3 bus/raw.<source>/...
    cursor moves only after every event is written
   v   S3 notification on bus/raw.*  ->  SQS standard queue usep-<env>-raw-events  (5 receives -> dead-letter queue)
[2] Pipeline Lambda   usep-<env>-pipeline     (src/usep/adapters/aws_lambda/pipeline_handler.py)
    parse+normalize -> redact -> label -> map to ontology -> gate G1 -> write evidence -> publish
   v
    bus/entity.<domain>/...   node and edge candidates        bus/quarantine/...   records that failed
    bus/evidence.<family>/... one pointer per evidence object: the handoff to chunking and the LLM team
```

Seven sources: Jira, GitLab, GitHub, Confluence, Figma, ServiceNow, Azure DevOps. The pipeline stops at entity candidates. The entity resolver, steward review, fabric writer, PostgreSQL commit and projectors come next and are not built.

**Per snapshot** (`src/usep/pipeline/`, module map in its README): normalize (one parser per source) -> redact secrets and personal data -> label (sensitivity 0 to 3, ACL state, owners-only) -> map through the application pack -> translate states through the project pack -> gate G1 -> write redacted evidence -> publish. Link rules then add `references` and `documents` edges with method, rule and confidence; their targets are published pending resolution.

**Delivery is at-least-once and unordered** (standard SQS). Snapshots, evidence and quarantine objects are keyed by checksum and written once; entity events carry an `idempotency_key`; consumers pick by `source_version`, not arrival order.

## S3 layout (one bucket per environment, `usep-<env>-data`)

| Prefix | Holds |
|---|---|
| `raw/<source>/<id>/<sha256>.json` | immutable source snapshots (unredacted; encryption by KMS) |
| `bus/<topic>/p<NNN>/<uuid7>.json` | events, partition = crc32(tenant:key) mod 16; `bus/_offsets/` holds consumer positions |
| `state/connectors/<source>.json` | sync cursor |
| `evidence/<system>/<object>/<id>/<sha256>.<labelhash>.json` | normalized, redacted text with provenance, labels, ACL, egress decision and the keys and URLs it cites. A changed ACL writes a new object |
| `quarantine/<system>/<id>/<sha256>.json` | reason code and field names, never content |

## Topics

`raw.<family>` (jira, gitlab, github, confluence, figma, servicenow, ado), `entity.<domain>` (business, architecture, product, security, operations, platform, testing), `evidence.<family>` (same families as raw), `quarantine`, `ontology.release`. Events carry references, not payloads, and a `tenant_id`. Schemas are in `src/usep/pipeline/topics.py`.

## Quarantine reason codes

| Code | Meaning | Usual fix |
|---|---|---|
| `Q-UNMAPPED` | no mapping for this source object or type | add a mapping in the application pack |
| `Q-STATE` | a source state or code has no rule | add a row to the project pack's table |
| `Q-SCHEMA` | gate G1 failed (required attribute, vocabulary value, endpoint type) | read the reason, fix the mapping or source data |
| `Q-PARSE` | the snapshot is not the shape the parser expects (source schema drift) | fix the parser |

**Handoff to chunking and LLM teams:** read `evidence.<family>` events and the evidence objects they point at. Contract, labels, ACL handling and the egress rule: `docs/contracts/evidence.md`.

# Run and test

Use the project's virtual environment; the system Python has none of the packages.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt -r services/connectors/requirements.txt

python -m pytest tests ontology/tests evals/tests -q      # run-time package, pipeline, ontology, evals
(cd services/connectors && python -m pytest -q)           # connectors (bare imports: run from this folder)
python ontology/tools/check_ontology.py
python evals/tools/check_golden.py

python scripts/demo_local.py --show     # whole flow on dummy data, no AWS (see scripts/sample_data/dummy.json)
python scripts/demo_local.py --only jira --out demo_out
```

The demo runs the real connector and pipeline code over an in-memory S3, with 18 made-up records across all seven sources. Each record states what it should do, including deliberate failures.

# Deploy (not yet validated)

```bash
scripts/build_lambda.sh        # builds build/connectors and build/pipeline
sam validate --lint --template platform-iac/lambda/template.yaml
sam deploy --template platform-iac/lambda/template.yaml --config-env dev \
  --parameter-overrides TenantId=<uuid> KmsKeyArn=<arn> OntologyPins=<pins> RepoHosts=<hosts>
```

`platform-iac/lambda/samconfig.toml` defines the stacks `usep-dev`, `usep-staging`, `usep-prod`. Names: bucket `usep-<env>-data` (global namespace; a taken name fails the deploy), functions `usep-<env>-connectors` and `usep-<env>-pipeline`, queues `usep-<env>-raw-events` and `usep-<env>-pipeline-dlq`. The template was written without `sam` or `cfn-lint` available. IAM is not least-privilege and the KMS key policy, Object Lock and retention are undecided.

# Configuration

Connectors (Lambda environment; list values are JSON, for example `["acme/pay"]`). Tokens come from the Secrets Manager secret named by `USEP_INGESTION_SECRETS_ARN` (JSON of `USEP_INGESTION_*` keys); an explicit environment variable wins.

| Variable | Meaning |
|---|---|
| `USEP_INGESTION_S3_BUCKET`, `USEP_INGESTION_TENANT_ID` | required in Lambda |
| `USEP_INGESTION_S3_REGION`, `_ENDPOINT_URL`, `_RAW_PREFIX`, `_CURSOR_PREFIX`, `_BUS_PREFIX`, `_BUS_PARTITIONS` | S3 settings (defaults `raw`, `state/connectors`, `bus`, 16) |
| `USEP_INGESTION_JIRA_` + `BASE_URL`, `EMAIL`, `API_TOKEN`, `JQL`, `PAGE_SIZE` | Jira |
| `USEP_INGESTION_GITLAB_` + `BASE_URL`, `PRIVATE_TOKEN`, `PROJECT_IDS`, `PAGE_SIZE` | GitLab |
| `USEP_INGESTION_GITHUB_` + `BASE_URL`, `WEB_URL`, `TOKEN`, `REPOS`, `PAGE_SIZE` | GitHub (Enterprise: `BASE_URL=https://<host>/api/v3`) |
| `USEP_INGESTION_CONFLUENCE_` + `BASE_URL`, `EMAIL`, `API_TOKEN`, `SPACE_KEYS`, `PAGE_SIZE` | Confluence |
| `USEP_INGESTION_FIGMA_` + `BASE_URL`, `ACCESS_TOKEN`, `FILE_KEYS` | Figma |
| `USEP_INGESTION_SERVICENOW_` + `INSTANCE_URL`, `USERNAME`, `PASSWORD`, `TABLES`, `PAGE_SIZE` | ServiceNow |
| `USEP_INGESTION_ADO_` + `ORGANIZATION_URL`, `PAT`, `PROJECTS`, `PAGE_SIZE` | Azure DevOps |

Pipeline Lambda:

| Variable | Meaning |
|---|---|
| `USEP_BUS_BUCKET` (required), `USEP_BUS_PREFIX`, `USEP_BUS_PARTITIONS`, `USEP_STORE_BUCKET` | bus and object store (store defaults to the bus bucket) |
| `USEP_ONTOLOGY_DIR`, `USEP_ONTOLOGY_PINS` | packaged ontology folder and comma separated `pack@version` pins |
| `USEP_ONTOLOGY_ALLOW_REFERENCE` | `true` to load `reference_only` packs. Needed today, because every pack is a placeholder |
| `USEP_TENANT_ID`, `USEP_ONTOLOGY_REFRESH_SECONDS` | enables switching on `ontology.release` events (checked at most every 60 s) |
| `USEP_CONSUMER_GROUP` | offset group for poll mode (default `c02-acquisition`) |
| `USEP_REPO_HOSTS` | hosts whose URLs count as repositories for `documents` edges (empty: rule off) |
| `USEP_JIRA_PROJECT_KEYS` | only these prefixes count as Jira keys (empty: a stoplist drops UTF-8, SHA-256 and similar) |

# Operations

- **Failed messages:** a message that fails five times lands in `usep-<env>-pipeline-dlq`. Nothing replays it yet; fix the cause, then redrive the queue by hand.
- **Quarantined records:** list `quarantine/` in the bucket or read the `quarantine` topic. Nothing consumes them yet (no steward review).
- **Replay:** invoke the pipeline Lambda with `{"poll": true}` after resetting a consumer's offsets (`S3EventBus.reset`). Handling is idempotent. Use either notifications or polling for normal operation, not both.
- **New ontology version:** ship the pack in the package, change `USEP_ONTOLOGY_PINS`, and publish an `ontology.release` event. A release naming a pack that is not in the package is refused and the current ontology stays (`ontology_error` in the result).
- **Adding a source:** see `src/usep/pipeline/README.md`.
