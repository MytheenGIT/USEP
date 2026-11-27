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

## How the code uses these files

One loader, `usep.ontology_runtime.load_ontology`, reads this folder at run time. `src/usep/ontology/` (labelling and the graph) is a read-only view over that loader's result, not a second reader. Nothing writes a definition.

- **Config** (`config/local.yaml`): `ontology.dir`, `ontology.packs` (the exact packs a tenant pins, by id), `ontology.allow_reference_packs`, `ontology.require_signed`. With `ontology.dir` unset the gate is off and nothing is pinned.
- **Loader** (`ontology_runtime/loader.py`): loads the core and the pinned packs and fails closed: a missing pack, a pack that needs a different core, a `reference_only` pack without permission, two packs at one level defining one concept, or a mapping to an unknown concept or attribute. It also computes a digest of every defining file (line endings normalised).
- **Systems** (`systems.yml` in an application pack): each registered system must map to a known core type, be registered once, and name only regulatory scopes that a pinned pack defines. Nothing reads the scope at run time yet (OI-63).
- **Gate G1** (`ontology_runtime/gate.py`, run by the pipeline after the cheap checks and before linking): the app pack mapping turns a record's `kind` into a core concept; required attributes and enumerated values are checked. A record that fails is quarantined as `Q-SCHEMA`. A source object with no mapping follows the mapping file's `on_unmapped` (`quarantine` for Jira, `evidence` for Git and Confluence).
- **Pins**: every context package carries `ontology_version` (the core version) and an `ontology` block (core, each pack id, level and version, and the digest). The seal covers it, and a different pin never reuses a cached package.

Pack CI (`tools/check_ontology.py`) still decides whether a pack is allowed to exist (additive only, policies only tighten). The loader trusts a pack that passed it. The run-time validator reads the YAML, not the Turtle shapes, so rdflib stays out of the run-time path.

Signing and the registry (C-06, C-07) are built in `src/usep/registry/` (ADR-20, proposed): signed immutable releases, a trust store, per-tenant pins, `scripts/registry.py`, a release workflow and IaC. Not yet exercised: the IaC and workflow have never run, and no production signing key exists. Dotted source paths map at any depth. Still open: the project pack's state translation (`state_tables.py`) beyond the reference rows.

## Ingestion run-time (`src/usep/ontology_runtime/`)

A second run-time loader, used by the ingestion pipeline (`src/usep/pipeline/`). It sits beside `src/usep/ontology/` above, which serves labelling and the graph projection. Both read the same definitions; they overlap (bundle, gate G1) and should be unified, which is a decision for the owners of each (see `docs/review/ontology-owner-review.md`).

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
- Pack signing: packs in Git keep `signed: false` and `signature_ref: null`; the signature lives in the registry release (ADR-20), and `config/registry/trusted_keys.yaml` is empty until the platform lead creates the KMS key. Nothing here is published.
