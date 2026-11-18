# USEP: the product repository skeleton

Layout from RM 11.1. This is one Git repository. It holds definitions only: code, infrastructure code, ontology, harnesses, policies, evaluation assets and ADRs. Runtime data (the four stores, evidence, events), secrets, keys and run state are never committed; `.gitignore` blocks them. Plans, status and evidence go in `../phases/`; reference goes in `../knowledge/`.

Current content: the repository setup (`.gitignore`, `.gitattributes`, `.editorconfig`, `.env.example`, `CODEOWNERS`, `requirements-dev.txt`), the ontology in `ontology/` (see `ontology/README.md`), and a draft golden set with its checker in `evals/` (see `evals/README.md`). Empty folders carry a `.gitkeep`. Everything else is an empty skeleton until Sprint 1 starts.

Status: definitions only, no product code yet. The proposals (ontology attributes, golden set entities, freshness and fetch design) are pending ARB or SME review (OI-49 and the open ADRs in `../knowledge/08-conflicts-and-open-items.md`). Nothing here is signed or published.

## Git setup

- Default branch `main`. Protect it; merge by pull request only, with CODEOWNERS review (HLD 6.2 change path for `ontology/`).
- Line endings are LF (`.gitattributes`), so signed packs and canonical hashes are stable across machines.
- Never commit: `.env` files, keys, certificates, `*.tfstate`, database dumps, Kafka or graph data, evidence or sealed-package exports, model weights, Office or PDF files. Use Vault references.
- `CODEOWNERS` lists roles, not people. Replace each role with a team handle when the owners are named.
- Run the checks before every push: `python ontology/tools/check_ontology.py`, `python -m pytest ontology/tests -q`, `python evals/tools/check_golden.py` and `python -m pytest evals/tests -q`.
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
