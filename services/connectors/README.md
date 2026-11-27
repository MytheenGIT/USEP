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

Chunker, Embedding Worker, Link Resolver, Review Event Capture, Claim Extractor and
Conformance Checker are not referenced by this layer at all -- they
consume its output, they don't participate in ingestion.

## Ingestion path (source to S3)

`SyncService` runs each scope through the shared code in `src/usep` (HLD C-01, LLD 2.1):

1. `CursorManager.start_batch(source, scope)` gives the resume point: the stored cursor minus the overlap window.
2. The connector fetches the scope from that point. Every HTTP call waits for a rate-limit token, and is
   retried with back-off on 429 and 5xx, honouring `Retry-After` (LLD 4.3; `common/client_base.py`).
3. Each document goes to `RawPayloadWriter.write`, with an envelope (`_usep`) that `SyncService` adds: object type,
   scope, checkpoint, source version, extraction time and the source's access attributes. The writer scans for
   secrets and personal data (quarantine on a hit), skips unchanged content, keeps the data key in the
   `raw_object` index, encrypts the document (AES-256-GCM, one key per object), puts it in S3 under
   `raw/<tenant>/<source>/<scope id>/<type>/<id>/<hash>.json`, and publishes a reference-only event that carries
   the source version, extraction time and access attributes. `acl_ref` is `owners-only` until a permission
   mapping exists (LLD 4.4). A JQL query or URL scope is stored in the key as a short hash.
4. The cursor moves only after the writes, and never past an object whose write failed. That object is
   fetched again on the next run.
5. Every run has one hash-chained trail in the `audit_event` table (one chain per run id, UPDATE and DELETE
   blocked by a trigger on Postgres) and one `run_snapshot` row with the configuration in effect, secrets left out.

Settings the service will not start without: `USEP_INGESTION_TENANT_ID` and `USEP_INGESTION_DEV_KEK_B64`, plus
`USEP_INGESTION_S3_BUCKET` when the raw store is `s3`. AWS credentials come from the usual boto3 chain.
Figma file keys are ignored until `USEP_INGESTION_FIGMA_DPIA_APPROVED=true` (ADR-025, O-05).

### Run it

While S3 is not connected, raw objects land as files in the repo folder and S3 is a setting away
(`USEP_INGESTION_RAW_STORE=file` is the default; `s3` switches to the bucket). Both stores use the same keys
and the same encrypted bytes.

```bash
cd services/connectors
cp .env.example .env     # tenant id, key, API token, source values
docker compose up --build    # Postgres and the service on http://localhost:8000
```

```bash
curl -X POST "http://localhost:8000/sync/jira" -H "Authorization: Bearer $USEP_INGESTION_API_TOKEN"
```

What you can check afterwards (all under `services/connectors/output/`, which is git-ignored):

- `output/raw/raw/<tenant>/<source>/<scope id>/<type>/<id>/<hash>.json`: the raw objects, encrypted.
- `output/<source>/<run>.json` and `<run>.summary.json`: the readable result of each run, without any document the
  writer quarantined. These files are not encrypted; set `USEP_INGESTION_JSON_SINK_ENABLED=false` before real data.
- `docker compose exec connectors python -m tools.read_raw` lists what landed, and `... read_raw <object_key>`
  decrypts one object with the key from `.env`.

To use S3 instead: create the bucket first (block public access, versioning and Object Lock on, server-side
encryption), then set `USEP_INGESTION_RAW_STORE=s3`, `USEP_INGESTION_S3_BUCKET`, `USEP_INGESTION_S3_REGION` and AWS
credentials (or a role). The service checks the bucket at start-up and refuses to start if it cannot use it; it only
warns if versioning or Object Lock is missing, since those are bucket settings it cannot enforce.

The service will not start if the database or the raw store cannot be used.

Still development-only and to be replaced before real data (decisions pending, see `docs/ingestion-open-decisions.html`):

- Write-once protection is the bucket's own setting (versioning, Object Lock); the service only warns when it is missing.
- Key wrapping uses one local key (`usep.adapters.local_kek`). The HLD wants Vault or KMS (open item O-04).
- `LogEventPublisher` only logs. The `raw.<family>` topic on Kafka needs its adapter and ADR-037 (O-19).
- Source tokens still come from environment settings. The Vault references are open item O-18 (ADR-036).
- The Postgres tables are created at startup (`create_all`); there is no migration tool yet.
- The readable run output in `output/` (`USEP_INGESTION_JSON_SINK_ENABLED`, on by default for now) is unencrypted.
  Turn it off before real data. Jira attachments, when downloaded, are also saved unscanned and unencrypted under
  `output/binaries`; they do not go through the writer yet.

Not built yet: the 24-hour reconciliation and tombstones, the connector state machine, dead-letter storage,
webhooks, retention clean-up, and normalization (C-02). See the decisions document for why and what each needs.

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

## Sources, scopes, cursors and failures

**Every source is optional.** An admin may have no Jira or no Figma, so nothing is read from a source until it is
selected with `USEP_INGESTION_<SOURCE>_ENABLED=true`. A selected source must then be complete: the service lists
every missing or wrong value at once and refuses to start (for example Jira without an email, a token, or any JQL
or project key). Values for a source that is not selected are ignored (a warning says so), and a service with no
source selected starts and reads nothing.

Each selected connector has one or more **scopes**, and each scope is synced and checkpointed on its own
(cursor key `<source>:<scope>:live`). Lists can be comma-separated or JSON.

| Source | Required when selected | What to read (as many as needed) |
|---|---|---|
| Jira | `BASE_URL`, `EMAIL`, `API_TOKEN` | `PROJECT_KEYS` (`ENG,OPS`: each key is one whole project) and/or `JQL_QUERIES` (one JQL per line, or JSON) and/or `JQL`. At least one of the three. |
| Confluence | `BASE_URL`, `EMAIL`, `API_TOKEN` | `SPACE_KEYS` (`ENG,OPS`, space URLs or page URLs). At least one. |
| GitLab | `PRIVATE_TOKEN` (`BASE_URL` defaults to gitlab.com) | `PROJECT_IDS` (ids, `group/project` paths or URLs) and/or `ALL_MEMBER_PROJECTS=true` for every repository the token's user is a member of (archived ones skipped, up to `MAX_MEMBER_PROJECTS`, re-discovered every `SCHEDULER_SCOPE_REFRESH_MINUTES`). |
| GitHub | `TOKEN` (`BASE_URL` defaults to api.github.com) | `REPOSITORIES` (`owner/repo`, links or SSH links) and/or `ALL_MEMBER_PROJECTS=true` for every repository the token's user can reach (archived skipped, up to `MAX_MEMBER_PROJECTS`). |
| ServiceNow | `BASE_URL`, `USERNAME`, `PASSWORD` | `TABLES` (`incident,change_request,problem`; each is its own scope) and an optional `QUERY` (an encoded query that narrows every table). Read-only integration user. |
| Figma | `ACCESS_TOKEN` | `FILE_KEYS` (keys or URLs; `?node-id=` limits it to those pages or frames). Stays off until `DPIA_APPROVED=true`. |

Project keys and space keys go into JQL and CQL, so only plain keys are accepted (no quotes or operators). A JQL
query is the admin's own: write it without a cursor, the service adds one; Jira rejects a bad one.
`ALL_MEMBER_PROJECTS` can pull in repositories nobody approved (LLD 4.1: scopes are approved by a data owner), so it
is off unless asked for.

Two endpoints show and test the configuration (both need the bearer token):

- `GET /sources` lists every source: selected, running, its scopes, and why it is not running. No secrets.
- `POST /sources/<source>/check` asks the source, with read-only calls, whether the credentials and every scope
  work: Jira runs each query for one issue, Confluence opens each space, GitLab opens each repository, Figma reads
  each file's metadata. A wrong project key or space key shows up here instead of as an empty run.

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
pip install -e ".[crypto,s3]"            # from the repo root: the shared code in src/usep
pip install -r services/connectors/requirements.txt
cd services/connectors && uvicorn main:app --reload
```

Configure via environment variables, e.g. `USEP_INGESTION_JIRA_BASE_URL`,
`USEP_INGESTION_JIRA_EMAIL`, `USEP_INGESTION_JIRA_API_TOKEN`,
`USEP_INGESTION_GITLAB_PROJECT_IDS`, `USEP_INGESTION_CONFLUENCE_SPACE_KEYS`,
`USEP_INGESTION_FIGMA_FILE_KEYS`, `USEP_INGESTION_DATABASE_URL`. See
`config.py` for the full list and defaults. Never commit real tokens;
follow the repo-wide Vault-reference rule in the root `README.md`.

## Tests

Checks that need a real Postgres (tables, the audit trigger, several processes at once) are skipped unless
`USEP_TEST_DATABASE_URL` is set; the command is in `tests/integration/test_postgres.py`.

The Docker build needs network access to PyPI. On a network that re-signs TLS (a corporate proxy), the build fails with
`CERTIFICATE_VERIFY_FAILED` unless the proxy's root certificate is installed in the image; it is not included here.

```bash
pip install -e ".[crypto,s3]"            # from the repo root
pip install -r services/connectors/requirements-dev.txt
cd services/connectors && PYTHONPATH=../../src pytest
```

## Admin console API (what the UI calls)

The admin console lives under `/api` and is what `ui/` talks to. An admin signs in (`USEP_INGESTION_ADMIN_USERNAME` and
`_ADMIN_PASSWORD`; with none set, nobody can sign in), builds a **configuration**, and the service reads it and builds the
knowledge-graph view. Sessions are in memory and last `USEP_INGESTION_SESSION_TTL_HOURS` (8).

**No connector is mandatory.** A configuration holds only the connectors the admin switched on (`enabled: true`); the rest are
stored as not used and are never read. At least one must be on, and a connector that is on must be complete. Per connector:

| Connector | Fields | Rule |
|---|---|---|
| Jira | `base_url`, `email`, `api_token`, `project_keys` (many), `jql_queries` (many) | at least one project key or JQL query |
| Confluence | `base_url`, `email`, `api_token`, `space_keys` (many; keys or space links) | at least one space |
| GitLab | `base_url`, `api_token`, `project_paths` (many), `all_member_projects` | at least one repository, or `all_member_projects: true` |
| GitHub | `base_url` (optional), `api_token` **or** `auth_method: ssh_key` + `ssh_key`, `repositories` (many; names, links or SSH links), `all_member_projects` | at least one repository, or `all_member_projects: true` (token only) |
| ServiceNow | `base_url`, `email` (the username), `api_token` (the password), `tables` (many), `encoded_query` | at least one table |
| Figma | `api_token`, `file_keys` (many) | at least one file; refused until the DPIA is signed off (ADR-025) |

The secret is called a token everywhere (a password for ServiceNow). **SSH keys** (GitHub and GitLab): an SSH key cannot call a
platform API, so with `auth_method: ssh_key` the service runs `git` over SSH and reads the commit history (one document per commit):
no pull requests, merge requests, comments or reviews, and no "every repository" list. The key must be a whole private key without
a passphrase. It is written to a private temporary file for one command, deleted after, and never stored or logged. SSH is refused
unless the host's key is known: github.com and gitlab.com work out of the box (their published keys are built in); a self-hosted host needs the operator to give its key (`USEP_INGESTION_SSH_KNOWN_HOSTS` or `_FILE`): hosts are checked strictly, never
trusted on first use. The SSH path was tested against a local repository, not over a real SSH connection.

A connector can use `use_server_credentials: true` instead of typed ones when the server holds them. Typed tokens are held in
memory for one run and dropped; they are never stored, logged or returned.

| Method | Path | Returns |
|---|---|---|
| POST | `/api/auth/login`, `/api/auth/logout` | session token; 204 |
| GET | `/api/connector-defaults` | per connector: server base URL, whether the server holds credentials, and `blocked_reason` (Figma before the DPIA) |
| POST | `/api/connectors/{source}/test` | `{ok, message}`: signs in, runs each JQL, opens each space, repository or table (the connector's own `check`). The UI calls it by itself when a configuration is created |
| POST | `/api/connectors/{github,gitlab}/repositories` | the repositories the entered token can reach (`path`, `name`, `visibility`; up to 500, `truncated` beyond), for choosing from |
| POST | `/api/configurations` | 201, or 422 with `fields` keyed `name`, `connectors` or `<connector>.<field>` |
| POST | `/api/configurations/{id}/connectors` | Adds connectors to a configuration that is `ready` (body `{connectors: {confluence: {...}}}`). Returns it as `processing`; 422 if a connector is already in it, none is chosen, or a new one is incomplete; 409 if it is not ready |
| GET | `/api/configurations`, `/api/configurations/{id}` | configurations with `connectors` and a status per selected source |
| GET | `/api/configurations/{id}/graph` | the graph; 409 until `ready` |

**Adding a connector later.** A configuration that is ready can take more connectors. Only the new ones are read, so the earlier tokens
(which are not kept) are not needed: the graph is rebuilt from what the earlier connectors returned the first time. Each source's
documents are saved as readable JSON in `output/configurations/<id>/sources/<source>.json` for this, next to the run files (they are
not encrypted; keep them on the machine). A new connector that cannot be read is taken out again, and the configuration stays ready
with the graph it had and a note saying what could not be added. A configuration made before results were saved cannot take a new
connector (the graph would lose the earlier ones); the service says so before it uses the new token, and Edit and resubmit reads everything again.

A configuration is processed through the same ingestion path as a scheduled run: rate limit and retry, the raw payload writer into
the raw store, the audit trail and a run snapshot. Its cursors start empty, so the whole configuration is read and the graph is
complete. It is `ready` when every selected source was read; a source that was not selected never counts. Typed hosts are guarded
(https only, no private addresses unless `USEP_INGESTION_ALLOW_PRIVATE_SOURCE_HOSTS=true`, and an optional allow-list in
`USEP_INGESTION_ALLOWED_SOURCE_HOSTS`).

## Service API (machine use)

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

`/sync/*`, `/results/*` and `/sources` require `Authorization: Bearer <token>`, where the token is
`USEP_INGESTION_API_TOKEN` (from the environment or Vault, never committed). With no token set those
routes return 503. For local development only, `USEP_INGESTION_AUTH_DISABLED=true` turns the check off.
`/health` is always open.

`GET /results/{source}` is paginated with `limit` (default 50, max 200) and `offset`, ordered by each
run's `started_at` (newest first); the `X-Total-Count` header has the total. Unreadable run files are skipped.

## Docker

```bash
cd services/connectors
docker compose up --build   # builds from the repo root, so the image includes src/usep
```

This starts Postgres and the API. Put the Jira values in a `.env` file next to `docker-compose.yml`
(see `config.py` for the variable names). Never commit `.env`. Saved results are written to
`./output` on the host through a volume.


## Audit trail

Every call to the service, every console action, every ingestion run and the service's start and stop leave a hash-chained audit event. Each event holds who (the signed-in admin, or `api-client`), what, the result, the trace (run id, or none for console and API events), the app version, a request id (also returned as `X-Request-ID`) and the client address. Request bodies and query strings are never recorded, so no token, password or key reaches the trail.

`USEP_INGESTION_AUDIT_STORE` chooses where it lands; all three keep the same record and chain, so switching changes nothing else:

| Value | Where | Notes |
|---|---|---|
| `file` (default) | `output/audit/console.jsonl` and `output/audit/runs/<run id>.jsonl` | One JSON line per event, appended and fsynced. Check a file with `usep.adapters.local_files.audit.verify_audit_file`. Git-ignored with the rest of `output/`. |
| `postgres` | table `audit_event` | Append-only by trigger. |
| `s3` | `audit/<tenant>/<console or run id>/<time>-<id>.json` in the bucket | One immutable object per event, fits Object Lock. A new process starts a new chain (see the `shortcut` note in `usep/adapters/s3/audit.py`). |

The file trail is not write-once: anyone with the folder can edit it, but the chain shows it. Retention and export are still open (D-09).
