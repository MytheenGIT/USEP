# Evidence contract, version 1

For the chunking, embedding and LLM teams. Evidence is the normalized, redacted text of one source record with its
provenance and labels. It is what you read; the raw source payload (`raw/`, unredacted) is not for you.
Tests: `tests/pipeline/test_evidence_contract.py` fails if this document and the code drift apart.

## How you find it

Subscribe to the topic `evidence.<family>` (family = jira, gitlab, github, confluence, figma, servicenow, ado). One event per
evidence object that has text. The event is a pointer plus the decision fields, so you can skip or route without opening it.

| Event field | Meaning |
|---|---|
| `evidence_ref` | `s3://<bucket>/evidence/...` the object to read |
| `source_system`, `source_object`, `source_id`, `source_version`, `source_url` | where it came from. `source_system` is `git` for GitLab, GitHub and ADO pull requests |
| `snapshot_ref`, `checksum` | the raw snapshot it was built from |
| `retrieved_at` | when the connector fetched it |
| `sensitivity`, `acl_state`, `owners_only`, `acl` | labels. See below |
| `egress` | `{"external_model": bool, "reasons": [...]}`. See below |
| `ontology` | digest of the ontology release it was built under |
| `idempotency_key` | dedupe on this. Delivery is at least once |

The event envelope carries `tenant_id`. Events are not ordered: for one `(source_system, source_id)` keep the evidence with
the newest `retrieved_at`, then the highest `source_version`.

## The evidence object (JSON, written once, never changed)

`schema_version` (1), `tenant_id`, `source_system`, `source_object`, `source_id`, `source_version`, `source_url`,
`snapshot_ref`, `checksum`, `retrieved_at`, `title`, `text`, `labels`, `sensitivity`, `acl_state`, `owners_only`, `acl`,
`egress`, `redaction`, `refs`, `ontology`.

- `text`: redacted plain text. Headings are `#` lines and list items are `- ` lines. Jira includes comments; GitLab and
  GitHub include commit messages and human comments or reviews. **Diffs and code are not included.**
- `labels`: the source's own labels, lower-cased.
- `refs`: `jira_keys`, `repo_urls`, `confluence_page_ids` (Jira remote links, when present) and (Confluence) `parent_id` the text points at. Use them to link chunks to each other.
- `redaction`: counts by kind, never values.
- A changed ACL or label set writes a **new** object (the key ends in a hash of the labels), so an old object can be stale.

## Labels, ACL and access

- `sensitivity`: 0 public, 1 internal, 2 confidential, 3 restricted. It only ever goes up. Treat embeddings as restricted data.
- `acl_state`: `known` or `unknown`. `unknown` means owners only until a later sync states otherwise (fail closed).
- `owners_only`: true when the ACL is unknown or a restriction was stated. Do not serve this text to anyone but its owners.
- `acl`: `{known, scheme, principals, restricted, scopes}`. `principals` are the stated restrictions (`security_level:Finance`,
  `group:leads`, `visibility:private`). `scopes` say what governs access (`project:ABC`, `space:ENG`) and do not say who may
  read. **Carry `acl` and `sensitivity` onto every chunk and filter on them at query time.** Authorization happens inside
  retrieval, not after it.

## Egress

`egress.external_model` is true only if text may leave the platform boundary for an external model or embedding service.
Default policy: sensitivity at most 1, not owners-only, and redaction found no secret and no personal data. Unknown ACL
blocks, so most records are blocked today. Call `usep.pipeline.egress.assert_allowed(evidence)` before sending text out.
Nothing here enforces it for you: enforcement belongs in the model gateway (C-09), which does not exist yet.

## Not covered yet

- No `entity_id`. Evidence is keyed by `source_system` and `source_id`; link chunks to entities once the resolver exists.
- Deletions and permission removals at the source are not propagated. A removed object's evidence stays.
- Redaction is pattern based (secrets, emails, card numbers). It does not detect names or free-text personal data.
- Source ACLs are partly harvested: Jira security level, Confluence read-restriction groups, GitLab and GitHub visibility.
  Jira project roles, ServiceNow ACLs and ADO area permissions are not, so those records stay `unknown`.
