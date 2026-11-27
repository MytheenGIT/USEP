# ontology: the USEP world model, held in Git

Layer L4 (HLD 6). The core world model and the four pack levels live here as plain files. Packs are versioned,
signed and published from Git by pack CI (C-07) to the ontology registry (C-06). This folder holds definitions only.
It holds no tenant data and no data from a source system.

```
ontology/
  core/                  Core world model: concepts, relationship types, domains, vocabularies, policy hooks, baseline policies
  packs/
    industry/            Regulatory concepts, controls, vocabularies        (industry practice lead)   Phase 3
    org/                 Glossary, source precedence, policies, approvals,  (enterprise architect)     v0 in S6
                         Tier 3 list
    app/                 Systems mapped to core types, connector mappings   (application architect)    v0 in S6
    project/             Delivery vocabulary, workflows, definition of done (delivery lead)            OI-19
  shapes/                SHACL constraints (Turtle) for the core and for relationship endpoints
  templates/             Named, permission-aware query templates with depth and fan-out limits
  tools/check_ontology.py   Local pack CI: additive-only, policy, template and shape checks
  tests/                 pytest suite and synthetic fixture
```

## What each part holds (HLD 6 Table 9)

| Part | Files | Count |
|---|---|---|
| Core concepts | `core/concepts.yml` | 16 (plus the `Pack` meta node) |
| Relationship types | `core/relationships.yml` | 12 |
| Semantic domains | `core/domains.yml` | 7, each with an owner role |
| Constraints | `shapes/core-shapes.ttl`, `shapes/core-relationship-shapes.ttl` | cardinality, mandatory attributes, allowed values, temporal validity, endpoint types |
| Query templates | `templates/*.yml` | 8, each limited to depth 3 and fan-out 200 |
| Policy hooks | `core/policy-hooks.yml` | sensitivity, criticality, regulatory_scope, acl_state |
| Baseline policies | `core/policies.yml` | deny by default; owners only when permissions are unknown; Tier 3 never autonomous |

## Rules the checks enforce

- Packs add; they never delete or redefine a core concept, relationship or policy (ADR-08). Keys such as `remove` or `override` are rejected.
- Policies only tighten. A pack policy may deny, require approval or restrict to owners. It can never allow (HLD 6.1; CC-17).
- Two packs at one level that define the same term fail (CC-16).
- Every template filters on `tenant_id` (ADR-10), applies `{{access_predicate}}` inside the match (ADR-06), has a LIMIT, and goes no deeper than 3.
- Every core concept and relationship type has a shape.

## Run

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
python ontology/tools/check_ontology.py
python -m pytest ontology/tests -q
```

## Run-time package (`src/usep/ontology/`)

The files above are definitions. The run-time package loads and applies them. It reads the same YAML; pack CI (`tools/check_ontology.py`) checks the Turtle shapes.

- **Loader (`load_ontology(root, pins)`)**: reads the core and the pinned packs from a checkout. It collects every problem and raises one `OntologyLoadError`, so no partial ontology is ever returned (fail closed). It refuses a pack that is not pinned or not found, a wrong version, a reference-only pack (unless `allow_reference_only`), a pack needing another core version, a pack that redefines or removes a term, and a policy that would loosen access. A pin looks like `app.app-reference@0.1.0`.
- **Bundle (`OntologyBundle`)**: immutable. Concepts, relationships, vocabularies, mappings, policies, templates, precedence, glossary, the project pack's `workflow`, and a `release` (core version, pack versions, SHA-256 digest of every defining file). The digest lets a run say which ontology it used.
- **Gate G1 (`gate.py`)**: `map_record` selects the application-pack mapping for a source object (no match: `Q-UNMAPPED`); `validate` checks required attributes, vocabulary values, temporal validity and edge endpoint types (failure: `Q-SCHEMA`). A failure becomes a quarantine entry with a reason code and field names, never content.
- **State translation**: the mappings leave one step to the project pack, turning a source state into a core state (`src/usep/pipeline/state_tables.py` says which source field feeds which attribute and which table translates it). No rule means `Q-STATE`.
- **Release events (`events.py`)**: an `ontology.release` event carries versions and the digest, not definitions. A consumer reloads from its own checkout and switches only if its digest matches. The pipeline Lambda does this at most every `USEP_ONTOLOGY_REFRESH_SECONDS`; a release it cannot load is refused and the current ontology stays.
- **Used by**: the acquisition pipeline (`src/usep/pipeline/`), which calls the loader once per container and the gate per record. The ingestion flow is described in the root `README.md`.

Pack relationships and shapes: the application pack adds `references` and `documents` (`packs/app/app-reference/concepts.yml`, shapes in `shapes/packs/application/`). Pack CI requires endpoint shapes for application-pack relationships and validates every project-pack state table against the core vocabularies.

## What is a source fact and what is a proposal

- **From the sources:** concept names, relationship type names, the seven domains, the pack levels and what each adds,
  the four rules (additive, most specific wins, policies only tighten, same-level conflicts fail), the constraint
  "every Service has exactly one owning Team", the query template `impact_of_change` and its depth and fan-out limits,
  the four policy hook attributes, the approval tiers, and the precedence and winner rules.
- **Proposals (P), open item OI-49:** the attributes on each concept, the domain given to each concept, the endpoint
  signatures of each relationship type, the controlled vocabulary values, the YAML and Turtle file formats, the
  placeholder namespace IRI `https://usep.invalid/ontology/core#`, and the exact text of the eight templates.
- **Placeholders:** the `*-reference` packs are examples of shape. Their glossary, precedence order, system rows and
  definition-of-done items are placeholders until the owners decide. No real organization, system or person is named.

## Open points

- Where a pack keeps its own shapes. The Roadmap layout has one `shapes/` folder; this repo puts core shapes at the
  root and pack shapes under `shapes/packs/<level>/<pack>.ttl` (the application pack's are there; OI-49).
- Pack-level query templates are not supported yet (loader, check and golden set know only the eight core ones).
- Proposals awaiting the owner are listed in `docs/review/ontology-owner-review.md`.
- Where the engineering domain fragment lives (OI-18) and whether the pilot needs a project pack (OI-19).
- Pack signing: `signed: false` and `signature_ref: null` until C-07 exists. Nothing here is published.
