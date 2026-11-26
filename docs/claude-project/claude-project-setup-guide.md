# Setting up the shared USEP Claude Project

This guide creates one Claude Project for the whole team, so every person who works on the Engineering Context Layer starts from the same instructions, the same decisions and the same standards. Follow the steps in order. The whole setup takes about an hour for the project owner and about 15 minutes for each team member.

## What the Project is for, and what it is not

The Project holds shared context for design discussions, reviews, planning and story preparation. Writing and running code happens in Claude Code inside the repository, which reads `CLAUDE.md` automatically. The repository, and its `docs/adr/` folder, are the source of truth. If the Project and the repository disagree, the repository wins, and the Project knowledge is updated.

## Before you start

You need a Claude account on a plan that includes Projects, and the ability to share a Project with your team if you want one shared Project. Check the sharing option in the product's current help, because sharing depends on your plan and your organisation's admin settings. You also need access to the USEP repository, so you can copy the files from `docs/claude-project/`.

Choose one person as the project owner. The owner is responsible for updates. The recommended owner is the semantic architect, with the platform lead as backup.

## Step 1: Get the pack

Take the folder `claude-project/` from this package and commit it to the repository under `docs/claude-project/`, through a branch and a pull request like any other change. Ask the platform lead if you need write access. Confirm the version in `01-project-instructions.md` matches the version you are about to upload. Current version: 1.0, 25 Nov 2026.

The pack contains these files:

| File | Upload to the Project? | Purpose |
|---|---|---|
| `01-project-instructions.md` | Paste the block into the instructions field | Assistant behaviour and hard rules |
| `knowledge/02-decisions-register.md` | Yes | Decisions D1 to D17, superseded spec items |
| `knowledge/03-architecture-reference.md` | Yes | Modules, components, stores, flows |
| `knowledge/04-development-standards.md` | Yes | Patterns for code, tests, Git and checks |
| `knowledge/05-ontology-and-evaluation-rules.md` | Yes | Ontology change path, golden set rules |
| `knowledge/06-team-ownership-and-workflow.md` | Yes | Owners, workstreams, story flow |
| `knowledge/07-open-items.md` | Yes | Open items with owners and dates |
| `templates/story.md`, `adr.md`, `build-record.md`, `pull-request.md` | Yes, all four | Standard formats |
| `repo/CLAUDE.md` | No. Goes in the repository root. | Instructions for Claude Code |
| `claude-project-setup-guide.md` (this file) | Optional | Process reference for the team |

Do not upload `poc-module-spec.md` v0.3, `claude-project-setup.md` (the earlier guide), the review documents, the diagram sources, or any raw data. The spec v0.3 is superseded where it conflicts with the decisions register, and uploading it would bring back the superseded choices (Voyage AI, Procrastinate, 30-day raw JSON). `work-breakdown.md` can be uploaded after its owner confirms it matches the decisions register, because it predates decisions D1 to D17.

## Step 2: Create the Project

In Claude, open Projects, choose New project, and name it `USEP Engineering Context Layer (PoC)`. Use this description:

> Shared development workspace for the USEP Engineering Context Layer PoC. Ingests Jira, GitLab, Confluence, and later Figma and Azure DevOps; builds an ontology, a knowledge graph and hybrid retrieval; answers questions with cited sources and audit trails.

## Step 3: Paste the instructions

Open the Project's instructions and paste the text inside the code block in `01-project-instructions.md`, exactly as written. Do not add personal preferences here. Personal preferences go in your own account settings, if the product allows them.

## Step 4: Upload the knowledge files

Upload the files in the order listed above, so the files a reader needs first are the first ones the assistant sees: decisions register, architecture reference, development standards, ontology and evaluation rules, team ownership, open items, then the four templates. Check that each file uploaded with its full content and no truncation. Check the total size against the current knowledge limit in the product.

## Step 5: Share with the team

If your plan allows sharing a Project, open the Project's menu, choose Share, and invite each team member. Give everyone the same access level the owner has agreed (proposed: view and chat for all; edit for the owner and backup only). If sharing is not available on your plan, each team member creates the Project from Steps 2 to 4 using the same files from the repository. The version number in `01-project-instructions.md` is then the check that everyone is aligned.

## Step 6: Set up the repository and Claude Code

Commit `docs/claude-project/` and `repo/CLAUDE.md` (copied to the repository root as `CLAUDE.md`). Then update the repository README, which refers to `../templates/` and `../knowledge/`. Those folders are outside the repository, so change those references to `docs/claude-project/templates/` and `docs/claude-project/knowledge/`. Each developer opens the repository in Claude Code, which reads `CLAUDE.md` automatically.

## Step 7: Onboard each team member

Each person completes this checklist once.

| Check | Done when |
|---|---|
| Has access to the Project | The Project appears in their list and opens |
| Has read the decisions register and the standards | They can name the five hard rules (tenant, write paths, audit, secrets, fail closed) |
| Has the repository and Claude Code | `CLAUDE.md` is loaded in their session |
| Has run the four checks on their machine | All four commands pass on a fresh clone |
| Knows the templates | They have filled a story template for one of their stories |
| Knows their owner role and workstream | Their name is confirmed in `06-team-ownership-and-workflow.md` |

Ask each person to start their first conversation with this prompt, changing the story key:

> I am working on story USEP-___ in workstream W_. Restate the inputs, outputs, tables, audit events, component, HLD section, ADR and test for this story, using the standards and the decisions register. List any open items it depends on. Do not write code yet.

## Step 8: Keep the Project current

The repository is the source of truth. Changes to the knowledge files are made in the repository, through a pull request to `docs/claude-project/`, reviewed by the semantic architect and the platform lead. After the pull request is merged, the owner replaces the affected files in the Project with the new versions, within one working day. The owner then updates the version number in `01-project-instructions.md` if the instructions changed.

When a decision is recorded as an ADR, add it to the decisions register and close the matching open item in `07-open-items.md` in the same pull request. Do not leave decisions only in conversations.

After a major change, tell the team to start new conversations. Older conversations carry the old assumptions.

## Step 9: Handle problems

If the assistant gives an answer that conflicts with an ADR, ask it to cite the ADR and the register entry it used. Then check the version of the file it read. If the Project knowledge is out of date, the owner updates it as in Step 8.

If the assistant asks for a decision the register does not cover, raise it at the team review and record the answer as an ADR. Do not answer it in the chat only.

If the assistant suggests a vendor, a folder, a table or a field that is not in the standards, ask it to list the decision that allows it. If none exists, treat the suggestion as a proposal and draft an ADR.

## Starter prompts for each workstream

Use these as the first prompt in a new conversation for each area.

| Area | Prompt |
|---|---|
| Infrastructure (Mytheen) | Draft the Docker Compose layout for the PoC on one AWS host (ADR-031), listing services, volumes, secrets as Vault references, and the checks that prove it starts. Flag anything that needs AWS account or Vault decisions. |
| Connectors (Debansha, Prasanth) | Restate the Jira connector's inputs (JQL, project, sync cursor, overlap window), outputs (raw JSON to S3, event to `raw.jira`), audit events and tests. Note that evidence snapshot points O-01 are open. |
| Ingestion and retrieval (Saurav) | Restate the retrieval query's inputs, tenant predicate, access predicate (ADR-030), fusion method and the relevance wording. List the tests against the golden set. |
| Ontology and metrics (Akhil) | Propose the PoC pack entries for KPI, Change-to-Service and review events (ADR-034). Check each against the core and the change path. |
| Evaluation (Bibin, Balu) | Explain how the engineering-graded golden set is run and how results are labelled. Do not describe any result as accuracy. |

## Checklist for the project owner

| Task | Done |
|---|---|
| Pack copied to `docs/claude-project/` in the repository | |
| Instructions pasted and version confirmed | |
| Knowledge files uploaded in order, full content checked | |
| Templates uploaded | |
| Sharing set up, or each member has the same files | |
| `CLAUDE.md` committed at the repository root | |
| Repository README references updated | |
| Backup owner named | |
| Onboarding checklist sent to the team | |
