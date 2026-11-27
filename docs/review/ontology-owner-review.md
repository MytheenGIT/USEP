# Ontology review pack: proposals awaiting the ontology owner

Everything below was added while building the C-01/C-02 ingestion path. It is a proposal (P) until the named owner
accepts it. Nothing here is published, signed or tenant data. Open points are decisions, not tasks already done.

## 1. Decisions needed

| # | Decision | Owner | Recommendation |
|---|---|---|---|
| D1 | Keep `references` and `documents` as application-pack relationships, or promote them to the core? Promotion changes HLD 6 Table 9 (twelve types) and `check_ontology.py`. | Lead ontology engineer, ARB | Keep in the pack for the pilot. Promote only if more than one application pack needs them. |
| D2 | **Built, awaiting acceptance.** Pack-level query templates live in `packs/<level>/<pack>/templates/`, listed in the pack manifest under `files.templates`, with the same rules as core templates (tenant filter, access predicate inside the match, LIMIT, depth and fan-out caps). Names start with the pack folder (`app_`), so a clash with a core name is impossible; two packs cannot define one name. Only pinned packs' templates load. Pack CI checks them against the core's and the pack's own concepts and relationships; the golden-set check needs an easy, medium and hard item for each. First two: `app_references_of`, `app_documents_of` (8 golden items, eng-183 to eng-190, synthetic). Not done: the context engine's table of runnable templates does not exist yet (`services/context-engine` is empty), so it cannot run them. | Lead ontology engineer | Accept, then keep the context engine's runnable list in step with the pack templates when it is built. |
| D3 | `Person` stays role-only (no names, emails or aliases). Identity resolution from the source design notes is not built. | Security architect, data owner | Keep. Ownership comes from CODEOWNERS and group mappings through `owns`. |
| D4 | One `source_system` value `git` is shared by GitLab, GitHub and ADO pull requests. Precedence cannot rank one above another. | Lead ontology engineer | Accept for now, or split into `gitlab`, `github`, `ado_git` (touches the mappings and the precedence file). |
| D5 | Source-id formats: GitLab `<project>!<iid>` (unchanged), GitHub `github:<owner/repo>#<n>`, ADO PR `ado:<project>/<repo>!<id>`, ADO work item `<project>#<id>`, Jira key, ServiceNow `number`. | Platform engineer | Confirm. These become the resolver's identity keys. |
| D6 | A link from an MR to a Jira Task or Bug is Change to Change. Core `implements` does not allow it, so it is `references`. | Lead ontology engineer | Accept `references`. The resolver may upgrade Change to Requirement or Decision to `implements`. |
| D7 | **Resolved in code.** There is now one loader (`usep.ontology_runtime.load_ontology`). `usep.ontology` is a read-only view over it, and the old second loader and gate were removed. `tests/test_ontology_unified.py` compares what labelling and the graph see against a golden snapshot taken from the old loader. One difference: the vocabularies now include `domains`. The two mapping field syntaxes (plain name in `git.yml`, dotted path in `jira.yml`) still coexist; the gate accepts both. The loader now reads only the mapping files a pack manifest lists, and it checks that mapped fields are attributes of the target concept. | Lead ontology engineer | Confirm, and pick one field syntax. |
| D8 | Egress and classification defaults for model use: external model only if sensitivity is at most 1, the ACL is known and unrestricted, and redaction found no secret or personal data. Unknown ACL blocks, which today blocks nearly everything. | Security architect, data owners | Confirm or relax per source once ACL harvest widens. A policy change in `EgressPolicy`, not code. |

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
  page read restrictions, GitLab project visibility, GitHub repository visibility, ADO project visibility (pull requests only). Everything else is unknown.

## 3. Defects found, not fixed here
- `industry/retail-reference` did not load (missing vocabularies, a scalar `from`/`to`, a `GOVERNED_BY` shadowing the core `governed_by`). Fixed: the run-time loader now reads a pack's `terms` vocabularies and accepts a scalar relationship end, the redundant relationship was removed, and the shape check now covers every pack. `tests/test_all_packs_load.py` loads every pack so pack CI cannot miss this again.
- The Jira client did not request `issuetype` or `updated`, so no issue could map and the cursor could not advance. Fixed.
- Evidence is written once mapping succeeds and before gate G1, so a record quarantined at G1 still has evidence.

## 4. Not covered by the ontology tooling yet
- Cardinality (one owning Team per Service), conflict handling and append-only assertions need the graph and the fabric
  writer, which do not exist.
- No golden-set items for `references` or `documents`; no precision measurement. The source design notes suggest labelling
  about 100 edges per relation type before trusting them.
- Pack signing and the registry release workflow (C-06, C-07). The pipeline switches releases on an `ontology.release`
  event only among versions shipped in its package, and refuses the rest (reason returned as `ontology_error`).
