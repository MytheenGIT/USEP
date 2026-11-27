# Ontology review pack: proposals awaiting the ontology owner

Everything below was added while building the C-01/C-02 ingestion path. It is a proposal (P) until the named owner
accepts it. Nothing here is published, signed or tenant data. Open points are decisions, not tasks already done.

## 1. Decisions needed

| # | Decision | Owner | Recommendation |
|---|---|---|---|
| D1 | Keep `references` and `documents` as application-pack relationships, or promote them to the core? Promotion changes HLD 6 Table 9 (twelve types) and `check_ontology.py`. | Lead ontology engineer, ARB | Keep in the pack for the pilot. Promote only if more than one application pack needs them. |
| D2 | Pack-level query templates. The loader, `check_ontology.py` and the golden-set check only know the eight core templates, so the new relationships have no template and no golden items. | Lead ontology engineer | Decide where a pack template lives, then extend the three tools. Until then, nothing can query `references` or `documents`. |
| D3 | `Person` stays role-only (no names, emails or aliases). Identity resolution from the source design notes is not built. | Security architect, data owner | Keep. Ownership comes from CODEOWNERS and group mappings through `owns`. |
| D4 | One `source_system` value `git` is shared by GitLab, GitHub and ADO pull requests. Precedence cannot rank one above another. | Lead ontology engineer | Accept for now, or split into `gitlab`, `github`, `ado_git` (touches the mappings and the precedence file). |
| D5 | Source-id formats: GitLab `<project>!<iid>` (unchanged), GitHub `github:<owner/repo>#<n>`, ADO PR `ado:<project>/<repo>!<id>`, ADO work item `<project>#<id>`, Jira key, ServiceNow `number`. | Platform engineer | Confirm. These become the resolver's identity keys. |
| D6 | A link from an MR to a Jira Task or Bug is Change to Change. Core `implements` does not allow it, so it is `references`. | Lead ontology engineer | Accept `references`. The resolver may upgrade Change to Requirement or Decision to `implements`. |
| D7 | Two ontology run-time packages now coexist: `usep.ontology` (bundle, gate, view; used by labelling and the graph projection) and `usep.ontology_runtime` (loader, gate, release events; used by the ingestion pipeline). Both define a bundle and a gate G1 with different APIs, and read the same definitions. Pack mapping field syntax also differs: `git.yml` uses plain attribute names, `jira.yml` dotted paths (the ingestion gate accepts both). | Lead ontology engineer, both package owners | Unify into one loader and one gate, keeping this branch's tests for both as the safety net. Until then do not change one without the other. |

## 2. What was added, by file

**Relationships** (`ontology/packs/app/app-reference/concepts.yml`, shapes in `ontology/shapes/packs/application/`)
- `references`: Change, Requirement, Decision to Change, Requirement, Decision, Incident.
- `documents`: Decision to Service, Application, API.
- Created by rules (`pipeline/links.py`): a Jira key in a title or branch (confidence 1.0), in a description or page body
  (0.9), in a comment (0.8); a repository URL on a configured host in a decision page body. Every edge carries method,
  rule and the matched token. Targets are published pending resolution with no type.
- Look-alike keys (UTF-8, SHA-256 and similar) are dropped by a stoplist, or by a per-tenant project-key allowlist.

**Mappings** (`ontology/packs/app/app-reference/mappings/`)
- `servicenow.yml`: incident to Incident, change_request to Change.
- `ado.yml`: Epic, Feature, User Story, Product Backlog Item, Requirement to Requirement; Task, Bug, Issue, Change Request
  to Change; anything else is quarantined as unmapped.
- `figma.yml`: a file is evidence only.
- GitHub reuses `git.yml` (pull request to Change, repository to Service).

**State tables** (`ontology/packs/project/project-reference/workflow.yml`), all squad-owned placeholders
- `pull_request_workflow`: opened to in_review, merged to released, closed to rejected.
- `jira_incident_severity` (priority name to sev1..sev4) and `jira_incident_status`.
- `servicenow_incident_severity`, `servicenow_incident_status`, `servicenow_change_workflow`: out-of-the-box numeric codes.
  An instance that customised its states must replace them.
- `ado_workitem_workflow`, `ado_requirement_status`: Agile, Scrum and Basic state names together.
- A value with no rule is quarantined `Q-STATE`, never guessed. The pack check now validates every table's targets
  against the core vocabularies and rejects an unknown table name.

**Classification defaults** (`pipeline/classify.py`, `ClassificationPolicy`)
- Default sensitivity 1 (internal). Labels raise it: public 0, internal 1, confidential/pii/gdpr/security 2,
  restricted/pci/secret/hr 3. Secrets found raise it to 3, personal data to 2, a restricted source ACL to 2. Nothing
  lowers it.
- ACL unknown or stale means owners only (HLD 4.5). A known ACL exists only for: Jira issue security level, Confluence
  page read restrictions, GitHub repository visibility. Everything else is unknown.

## 3. Defects found, not fixed here
- `industry/retail-reference` does not load: missing vocabularies `retail_channel` and `supplier_agreement_type`, and its
  relationship `GOVERNED_BY` has scalar `from`/`to` (the loader reads the strings as character lists) and shadows the core
  `governed_by` in a different case. Pack CI does not catch it because it never loads the pack. The new shape check is
  limited to application packs for this reason.
- The Jira client did not request `issuetype` or `updated`, so no issue could map and the cursor could not advance. Fixed.
- Evidence is written once mapping succeeds and before gate G1, so a record quarantined at G1 still has evidence.

## 4. Not covered by the ontology tooling yet
- Cardinality (one owning Team per Service), conflict handling and append-only assertions need the graph and the fabric
  writer, which do not exist.
- No golden-set items for `references` or `documents`; no precision measurement. The source design notes suggest labelling
  about 100 edges per relation type before trusting them.
- Pack signing and the registry release workflow (C-06, C-07). The pipeline switches releases on an `ontology.release`
  event only among versions shipped in its package, and refuses the rest (reason returned as `ontology_error`).
