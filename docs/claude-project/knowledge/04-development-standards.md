# Development standards

These standards make every team member's code and documents follow the same patterns. They come from the repository README and the decisions register. Items marked (proposed) need team agreement at the first team review.

## 1. Repository layout

Use the layout in the repository README. Do not create new top-level folders. Each service has one folder under `services/`. Shared domain code goes in `src/usep/`. Ontology work goes in `ontology/` only. Infrastructure goes in `platform-iac/`. Decisions go in `docs/adr/`. Templates for stories, ADRs, build records and pull requests are in `docs/claude-project/templates/`.

Folders in the repo that the README mentions but do not exist yet (`../knowledge/`, `../phases/`, `../templates/`, `../config/`) are not in USEP-main. Until they are, use `docs/` inside the repository and say so in the pull request.

## 2. Language and frameworks

Python 3.12 and FastAPI are the default for every service (HLD 16, Table 34). Pydantic v2 for schemas. Any other language for a service (Go or Java 21 for a connector, for example) needs its own ADR. Other frameworks named in the spec v0.3 (SQLAlchemy 2, Alembic, psycopg 3, Procrastinate, python-gitlab, atlassian-python-api, httpx, OpenTelemetry SDK) are proposals until confirmed against HLD 16. Record the confirmed set in a single ADR.

Each new technology choice needs an ADR. The HLD reference profile is the default; anything outside it needs an accepted ADR first. Do not add LangGraph, Graphify or JEV until their ADRs are accepted.

## 3. Architecture rules

Keep code technology-agnostic. `domain/` and `ports/` import no vendor SDK. Vendor code lives in `adapters/<tech>/`. Connections are configuration keys plus Vault references, never literal values.

Only the fabric writer inserts into fact tables (ADR-05). Only action adapters write to sources. Nothing writes directly to a projection store. Postgres is the commit point (ADR-03).

Authorization is inside retrieval, not after it. Every query, including vector and full-text queries, carries `tenant_id` and the access predicate (ADR-06, ADR-10, ADR-030).

Fail closed (ADR-14). If a check, gate or dependency cannot run, the action does not proceed and an error is returned.

## 4. Naming and identifiers

Configuration keys use lower_snake_case with a service prefix, for example `gateway_session_ttl_hours`. Use the key catalogue, once it exists in `config/defaults.yaml` (proposed: create it in Sprint 1). Database tables and columns use lower_snake_case. Packages and modules use lower_snake_case. Classes use PascalCase. Environment variables use `USEP_` with upper snake case (see `.env.example`).

Generated IDs are UUID v7. Timestamps are UTC ISO 8601 with milliseconds, for example `2026-11-25T09:14:03.120Z`. Watermarks are event times, not processing times. Tenant identifiers are UUID v7 values, the same format as other IDs.

## 5. Audit, logging and data protection

Every read, write, external call and model call emits an audit event. An event carries the trace ID, actor, action, component, tenant ID, timestamp and version. Build the audit writer once and call it from every module. Do not write code that skips it.

Logs carry IDs, counts and status. They never carry prompt text, completions, source content, credentials or restricted values. Prompts and completions are stored in the evidence store and referenced by ID (ADR-028).

Never store or show SSN, Aadhaar, PAN, passport numbers, driver's license numbers, credit card numbers or patient records. The sensitive-data filter runs before storage, before any model call and before prompt storage. Log only redaction counts.

Credentials are never in code, images, prompts, logs or Git. They come from Vault references (proposed ADR-036 for the credential design).

Embeddings are restricted data (sensitivity 3). They are deleted with their source entity.

## 6. Testing

Every change includes tests. Use unit tests for domain logic and ports, and integration tests for adapters and stores. Retrieval and citation changes are checked against the golden set (see the ontology and evaluation rules). Golden set results for the PoC are engineering-graded and are not pilot accuracy evidence (ADR-035).

## 7. Checks before every push

Run these from the repository root:

```
python ontology/tools/check_ontology.py
python -m pytest ontology/tests -q
python evals/tools/check_golden.py
python -m pytest evals/tests -q
```

Once a service exists, add its tests to this list in its folder README and in the build record.

## 8. Git workflow

The default branch is `main`. It is protected. Merge only by pull request, with CODEOWNERS review (proposed as a team rule; see `.github` or GitLab settings when the host is confirmed).

Branch names: `<JIRA-KEY>-<short-slug>`, for example `USEP-412-source-config-migration` (proposed).

Commit messages: `<JIRA-KEY> <imperative summary>`, for example `USEP-412 Add source_config migration` (proposed). Keep each commit to one logical change.

Pull requests use `docs/claude-project/templates/pull-request.md`. Each pull request links the story, the component, the ADR, the test results and the build record.

Never commit: `.env` files, keys, certificates, `*.tfstate`, database dumps, Kafka or graph data, evidence or sealed-package exports, model weights, Office or PDF files from customers. `.gitignore` blocks most of these. Run `git status --ignored` before pushing.

## 9. File hygiene

Text files use LF line endings (`.gitattributes`). PowerShell scripts (`.ps1`) use CRLF. Files end with a newline. Use UTF-8. Indent Python with 4 spaces and everything else with 2 (`.editorconfig`).

## 10. Local setup on Windows

Create a virtual environment in the repository root:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

Do not commit `.venv`.

## 11. Documentation

Every decision gets an ADR from `docs/claude-project/templates/adr.md`. Every story cites its component, HLD section, ADR and test. Every delivered piece gets a build record from `docs/claude-project/templates/build-record.md`. Deviations from the HLD or LLD always list an exit criterion and an owner.

## 12. Error handling and responses

Return typed errors with a code, a message and a trace ID. Do not return stack traces, SQL, prompts or source content to users. Errors are logged with IDs and counts only.

## 13. Review checklist for every change

Does it carry `tenant_id` in every token and query? Does it emit an audit event for each action? Does it avoid vendor SDKs outside adapters? Does it fail closed? Does it keep secrets out of code and logs? Does it use UUID v7 and UTC timestamps? Does it add a test? Does it cite its story, component and ADR? Is there a build record?
