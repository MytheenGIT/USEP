# Ontology and evaluation rules

## 1. Ontology layout

The ontology lives in `ontology/` and is governed as code. It has five parts: `core/` (the USEP core), `packs/` (industry, org, app, project), `shapes/` (SHACL), `templates/` (query templates), and `tools/` and `tests/` (checks).

The core has 16 concepts: Capability, Application, Service, API, DataAsset, Team, Person, Requirement, Change, Incident, Decision, Policy, Control, Environment, Release and Test. It has 12 relationship types: owns, depends_on, exposes, consumes, realizes, implements, tests, deployed_to, governed_by, caused_by, decided_in and supersedes. There are 7 semantic domains and 8 query templates. The Pack meta node describes pack metadata.

Sources are mapped to the core through the app pack. Jira, GitLab and Confluence have mappings. Figma and Azure DevOps do not yet; add them through the app pack when their DPIAs are signed (ADR-025).

## 2. Change path

Ontology changes go through a pull request. CODEOWNERS review applies to every change in `ontology/` (`lead-ontology-engineer`). Changes to `packs/org/` also need the enterprise architect and the governance lead. Changes to `packs/app/` need the application architect. Changes to `packs/project/` need the delivery lead. Changes to `packs/industry/` need the industry practice lead.

Learning and users never change production meaning directly (HLD 6.2). A user-facing ontology editor, if built, proposes changes that enter this path. It does not edit the ontology.

Pack rules: packs are additive only. When two rules conflict, the most specific wins. Policies only tighten; they never loosen.

Core changes need ARB approval. The first industry pack needs ARB approval. The USEP ontology is still draft.

KPI, Change-to-Service and review-event concepts are missing from the core (guide OI-58, OI-59). For the PoC they go in a PoC pack, then move to core through the change path (ADR-034).

## 3. Ontology checks

Run `python ontology/tools/check_ontology.py` and `python -m pytest ontology/tests -q` before every push. A failed check blocks the merge.

## 4. Golden set

The golden set is in `evals/golden/`. The PoC draft has 182 items, all synthetic, of which 13 are permission-aware. The checker is `evals/tools/check_golden.py`. Run it and `python -m pytest evals/tests -q` before every push.

Rules for the PoC: results are engineering-graded and labelled as such. They are not pilot accuracy evidence (ADR-035). Do not claim accuracy in any document, slide or message. The HLD (8.2) requires at least 150 SME-graded items per domain before pilot. Named SMEs for each domain are open item O-07.

Golden items must not contain real customer data, credentials, or sensitive personal data. Use synthetic or sanitised content only.

## 5. Evaluation metrics

Retrieval and citation changes are evaluated against the golden set. Report retrieval relevance scores with the wording "retrieval relevance". Do not describe them as confidence in correctness.

Human-in-the-loop metrics (rework rounds, merge request rejections, ADR revisions) depend on the review-event concepts in the PoC pack (ADR-034). Do not compute them from ad-hoc fields in code.

## 6. Retrieval gates

The grounding gate for answers: commit at 0.98 or above, advisory at 0.85 or above (ADR-12). Results below advisory are not shown as answers.

## 7. Working on ontology in the Claude Project

Ask the assistant to restate a change in terms of concepts, relationships, pack and check results before drafting the change. Ask it to flag any concept or relationship that is not in the core, rather than inventing one.
