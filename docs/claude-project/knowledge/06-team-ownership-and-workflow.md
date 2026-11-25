# Team ownership and workflow

## 1. Owners on the task sheet

The task sheet (Semantic_Layer_Task.xlsx, about 60 populated rows across five tabs, dates 30 Nov to 4 Dec 2026) assigns work as follows.

| Person | Work area |
|---|---|
| Debansha | Connector start |
| Saurav | Ingestion, model access, retrieval, UI |
| Prasanth | Connector runtime, linking, claims, conformance |
| Mytheen | Infrastructure and storage |
| Akhil | Ontology, metrics, observability |
| Bibin and Balu | Evaluation |

Saurav holds all of ingestion as well as retrieval and UI. That is the heaviest load on the team. Rebalance it before Sprint 3.

The task sheet's items for Graphify and for a runtime ontology editor conflict with the decisions register. They should be changed: the graph store is Neo4j (ADR-019), and ontology changes go through the change path (knowledge/05).

## 2. Roles and CODEOWNERS

CODEOWNERS lists roles, not people. The roles are: platform-lead, lead-ontology-engineer, enterprise-architect, governance-lead, application-architect, delivery-lead, industry-practice-lead, harness-engineer, security-architect, context-engineering-lead and semantic-architect. Named owners for each role are open item O-08. Until they are named, GitHub and GitLab ignore the unknown handles, so reviews need to be requested by hand.

Mapping of workstreams to roles (proposed): Mytheen to platform-lead; Akhil to lead-ontology-engineer and delivery-lead for the project pack; Saurav to context-engineering-lead for retrieval; Bibin and Balu to context-engineering-lead for evaluation; Prasanth to application-architect for connectors. Confirm this at the first team review.

## 3. Workstreams

The PoC work breakdown (`work-breakdown.md`) splits the work into six workstreams, W1 to W6, with interface contracts between them. Use the workstream ID in every story and branch name so work can be traced to the split.

## 4. Story flow

1. The story exists in Jira with a key, component, HLD section, ADR and test named (`docs/claude-project/templates/story.md`).
2. Restate inputs, outputs, tables, audit events and the test (in the Claude Project or in the story).
3. Create a branch named `<JIRA-KEY>-<slug>`.
4. Build with tests. Run the checks in the standards document. Build with Claude Code using the repository's `CLAUDE.md`.
5. Write the build record (`docs/claude-project/templates/build-record.md`).
6. Open a pull request using the pull request template. Request review from the CODEOWNERS role.
7. Merge only after review and passing checks.

## 5. Where to work

Design discussion, reviews and planning happen in the Claude Project. Writing and running code happens in Claude Code, inside the repository, which reads `CLAUDE.md` automatically. Decisions made in either place are written to `docs/adr/` and are not left in chat.

## 6. Keeping the team aligned

The repository is the source of truth. The Claude Project's knowledge files are a copy of `docs/claude-project/`. When a change is merged to that folder, the knowledge file in the Project is replaced with the new version. The setup guide describes the steps.

Start a new conversation in the Project after a major change. Older conversations carry stale assumptions.

## 7. Meetings and decisions

Decisions that need the ARB, the sponsor or a named owner are listed in knowledge/07-open-items.md with the owner role and the sprint by which they are needed.
