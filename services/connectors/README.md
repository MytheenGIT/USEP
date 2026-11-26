# Connectors / Ingestion Layer (Phase 1)

Engineering Context Layer / RAG platform -- Phase 1 only: source
synchronization, retrieval, light normalization, and provenance. No
embeddings, chunking, vector storage, retrieval, or LLM calls happen here;
those are later phases.

## Scope

In scope: Scheduler, Jira/GitLab/Confluence/Figma connectors, source
retrieval, light normalization into `SourceDocument` subclasses, and
provenance metadata.

Out of scope (see task description): embeddings, LLM calls, chunking,
vector databases, hybrid/semantic retrieval, RAG answering, claim
extraction, conformance checking, AST parsing, coverage ingestion.

Owned elsewhere, represented here only as interfaces (`common/interfaces/`):
Raw Payload Writer, Sync Cursor Manager, Audit Writer. Chunker, Embedding
Worker, Link Resolver, Review Event Capture, Claim Extractor and
Conformance Checker are not referenced by this layer at all -- they
consume its output, they don't participate in ingestion.

The default implementations of those three interfaces
(`InMemoryCursorManager`, `NullRawPayloadWriter`, `StructlogAuditWriter`)
are non-persistent stubs that only exist so this service can run
standalone in dev/tests. Replace them with the real, owned-elsewhere
implementations before running this anywhere shared.

## Layout

Each source gets its own top-level folder holding its client, its
normalized models, and its connector. Shared/cross-source code lives in
`common/`, `db/`, and `api/`.

```
jira/           JiraClient, JiraDocument + related models, JiraConnector, ADF-to-Markdown (adf.py)
gitlab/         GitLabClient, GitLabDocument + related models, GitLabConnector
confluence/     ConfluenceClient, ConfluenceDocument + related models, ConfluenceConnector
figma/          FigmaClient, FigmaDocument + related models, FigmaConnector

common/
  source_document.py   SourceDocument base model + SourceType enum (shared provenance contract)
  sync_models.py       SyncResult / SyncResponse / SyncStatus
  connector_base.py    SourceConnector Protocol, ScopeFetch / ObjectError, cursor rule (next_cursor)
  client_base.py       BaseAPIClient (shared async httpx wrapper, size-capped downloads)
  binary_store.py      BinaryStore for attachments / frame exports (local default)
  timeutil.py          UTC ISO normalization used for cursors and source_version
  interfaces/          CursorManager / RawPayloadWriter / AuditWriter contracts (+ dev stubs)

api/            FastAPI routes (POST /sync/<source>, POST /sync/all, GET /health)
db/             SQLAlchemy models/repository for this service's own sync-run bookkeeping
tests/          Unit tests

config.py       Pydantic Settings (env var driven)
container.py    Composition root (DI wiring: clients -> connectors -> SyncService -> Scheduler)
sync_service.py SyncService: orchestrates connector + interfaces
scheduler.py    APScheduler wrapper: one interval job per source
logging_setup.py  structlog configuration
main.py         FastAPI app factory
```

> The `gitlab/` folder name shadows the third-party `python-gitlab` package
> (importable as `gitlab`) if that package is ever added to this service's
> virtualenv. Don't add `python-gitlab` or `GitPython` (`git`) as a
> dependency here; this connector only needs `httpx`.

## Scopes, cursors and failures

Each connector is configured with one or more **scopes**, and each scope is
synced and checkpointed on its own (cursor key `<source>:<scope>`):

| Source | Scope | Setting |
|---|---|---|
| Jira | a JQL query | `USEP_INGESTION_JIRA_JQL_QUERIES` (JSON list; falls back to `..._JIRA_JQL`) |
| GitLab | project id, `group/project` path, or repository URL | `USEP_INGESTION_GITLAB_PROJECT_IDS` |
| Confluence | space key, space URL, or page URL (page + descendants) | `USEP_INGESTION_CONFLUENCE_SPACE_KEYS` |
| Figma | file key or file URL (`?node-id=` limits it to those pages/frames) | `USEP_INGESTION_FIGMA_FILE_KEYS` |

Cursors and `source_version` are UTC ISO 8601 (`2026-11-26T10:00:00.000Z`).
A connector reports a single failed object (issue, MR, page, attachment) as an
`ObjectError` instead of raising; the run is then `partial`, and the scope's
cursor is held at the oldest failed object's version so the next run picks it
up again. A scope that cannot be read at all fails only that scope.

The scheduler registers one job per source and scope; each uses its source's interval unless
`USEP_INGESTION_SCHEDULER_SCOPE_INTERVAL_MINUTES` (JSON, `{"jira:project = ABC": 10}`) overrides it. A manual
`POST /sync/<source>` and a scheduled job never sync the same scope at the
same time; the second one is reported in `skipped_scopes`.

Retries, back-off and rate limiting are not implemented here yet (connector
runtime work); a 429 or 5xx currently becomes an object or scope error and is
retried on the next run.

Binaries: Jira attachments up to `USEP_INGESTION_JIRA_ATTACHMENT_MAX_BYTES`
(default 1 MB, LLD Q-SIZE) and, if `USEP_INGESTION_FIGMA_DOWNLOAD_EXPORTS=true`,
Figma frame renders are written to `<output_dir>/binaries`. Larger files keep
their metadata with `skipped_reason: "Q-SIZE"`.

## Adding a new source connector

1. Create a new top-level folder `<source>/` with `client.py` (httpx-based,
   auth + pagination for that API), `models.py` (a `<Source>Document(SourceDocument)`
   with its own structured fields), and `connector.py` (a `<Source>Connector`
   with a `scopes` property and `fetch_scope(scope, cursor) -> ScopeFetch`; set
   `source_version` on every document so the cursor can advance).
2. Register it in `container.py`'s `connectors` dict and add its settings block to `config.py`.
3. Add a `POST /sync/<source>` route in `api/routes/sync.py` (copy an existing one) and a scheduler interval in `config.py`'s `SchedulerSettings`.

`SyncService`, the scheduler loop, and the response contract are source-agnostic and need no changes.

## Running

```bash
pip install -r requirements.txt
uvicorn main:app --reload --app-dir services/connectors
```

Configure via environment variables, e.g. `USEP_INGESTION_JIRA_BASE_URL`,
`USEP_INGESTION_JIRA_EMAIL`, `USEP_INGESTION_JIRA_API_TOKEN`,
`USEP_INGESTION_GITLAB_PROJECT_IDS`, `USEP_INGESTION_CONFLUENCE_SPACE_KEYS`,
`USEP_INGESTION_FIGMA_FILE_KEYS`, `USEP_INGESTION_DATABASE_URL`. See
`config.py` for the full list and defaults. Never commit real tokens;
follow the repo-wide Vault-reference rule in the root `README.md`.

## Tests

```bash
pip install -r requirements-dev.txt
cd services/connectors && pytest
```

## API for the UI

Base URL: `http://localhost:8000` (or the compose service at the same port). The interactive
spec is served at `/docs` (Swagger UI) and `/openapi.json`, which a UI can use to generate a typed client.

CORS is enabled for the origins in `USEP_INGESTION_CORS_ORIGINS` (default: `http://localhost:3000`, `http://localhost:5173`).

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{"status": "ok"}` |
| POST | `/sync/{jira,gitlab,confluence,figma}` | One sync result, including documents (`?include_documents=false` to omit them; `?scope=...` repeatable, to run only those scopes) |
| GET | `/sync/{source}/scopes` | The configured scopes for a source |
| POST | `/sync/all` | A list of sync results, one per configured source |
| GET | `/results/{source}` | Summaries of saved runs, newest first: `run_id`, `status`, `started_at`, `finished_at`, `documents_count`, `errors` |
| GET | `/results/{source}/{run_id}` | Full saved run, including `documents` |

`source` is one of `jira`, `gitlab`, `confluence`, `figma`. A sync result has `run_id`, `status`
(`success`, `partial`, `failed`), `cursors` (scope to cursor), `skipped_scopes`, `object_errors`
and `errors`. Every document keeps its provenance fields (`source`, `source_type`, `source_object_id`,
`source_url`, `retrieved_at`, `scope`, `source_version`, `content_hash`, `acl`, `raw_payload`) plus
its structured fields, so the UI can show the same data the chunker will later use.

Example from a UI hook (fetch, no extra dependencies):

```ts
export async function fetchJiraRuns() {
  const res = await fetch("http://localhost:8000/results/jira");
  if (!res.ok) throw new Error(`Failed to load runs: ${res.status}`);
  return res.json();
}
```

`/sync/*` and `/results/*` require `Authorization: Bearer <token>`, where the token is
`USEP_INGESTION_API_TOKEN` (from the environment or Vault, never committed). With no token set those
routes return 503. For local development only, `USEP_INGESTION_AUTH_DISABLED=true` turns the check off.
`/health` is always open.

`GET /results/{source}` is paginated with `limit` (default 50, max 200) and `offset`, ordered by each
run's `started_at` (newest first); the `X-Total-Count` header has the total. Unreadable run files are skipped.

## Docker

```bash
cd services/connectors
docker compose up --build
```

This starts Postgres and the API. Put the Jira values in a `.env` file next to `docker-compose.yml`
(see `config.py` for the variable names). Never commit `.env`. Saved results are written to
`./output` on the host through a volume.
