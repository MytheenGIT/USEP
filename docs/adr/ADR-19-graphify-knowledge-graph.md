# ADR-19: Graphify as the knowledge-graph representation and query layer

Status: **Proposed** (not accepted; the repo README bars adding Graphify until an ADR is accepted)
Owner role: semantic architect (CODEOWNERS `/docs/adr/`)
Date: 2026-11-25

## Context

USEP needs to represent labelled data as a knowledge graph, using the ontology in `ontology/` (16 core
concepts, 12 relationship types, plus industry, org, app and project packs). The data structure and the
labelling rules are not yet defined, so this ADR decides only the graph layer, not the ingestion.

Graphify (PyPI `graphifyy`, Graphify-Labs/graphify) is a tool that turns a codebase and its docs into a
queryable graph. We tested version 0.9.119 in a throwaway virtual environment (nothing added to the repo).

## What we found by running it

1. **Out of the box it does not understand our ontology.** Run on this repo with `extract --code-only`, it
   produced 699 nodes and 805 edges, but the nodes are files, classes and YAML keys, and 611 of the edges
   are the generic `contains`. It produced no `Service`, `Team` or `owns`. Using it as the extractor for
   ontology data would give a graph about our files, not about the enterprise.
2. **It accepts a graph we build ourselves.** A hand-written `graph.json` (node-link format, 7 ontology
   nodes, 6 edges named `owns`, `exposes`, `depends_on`, `consumes`, `governed_by`, `caused_by`) worked with
   `explain`, `path`, `affected`, `query` and `cluster-only`. Arbitrary relation names, the confidence
   labels (`EXTRACTED`, `INFERRED`, `AMBIGUOUS`) and our own `metadata` object were kept.
3. **It does not validate against an ontology.** It will accept any node and relation name. Validation stays
   ours (`ontology/tools/check_ontology.py`, the G1 gate).
4. **Its HTML view hides ontology detail.** `graph.html` shows labels, relations and confidence, but not the
   concept type or attributes (`Service`, `regulatory_scope` and `criticality` were absent from the page).
5. **Its schema is thinly documented.** The docs name the three output files and the confidence labels but
   list no node or edge fields, and document no Python API. The field names below were read from real
   output and may change between versions. The file carries `graph.schema_version: 1`.

## Decision (proposed)

Use Graphify as a **representation, query and reporting layer** over a graph that USEP builds from labelled
records. Do not use it as the extractor for ontology data.

- The graph model is vendor-neutral (`src/usep/graph/model.py`) and imports no Graphify code.
- A thin adapter (`src/usep/graph/adapters/graphify/export.py`) writes Graphify's `graph.json`. It writes
  JSON only and does not import the `graphifyy` package, so the repo takes no dependency until this ADR
  is accepted.
- Validation against the ontology (concepts and relationship types) happens before export, in our code.
- The concept goes in the node `type` field and attributes in `metadata`, so no information is lost.

## Consequences

- Positive: we get `path`, `affected` (reverse impact), `query`, community clustering and an MCP server
  without writing them. Edge confidence maps directly onto our `confidence` edge property.
- Negative: the UI cannot rely on `graph.html` to show ontology types or editable metadata. The UI tasks
  need their own view reading `graph.json`, which keeps the full `metadata`.
- Negative: the file format is vendor-controlled and lightly documented. The adapter is the single place to
  fix if it changes, and a contract test pins the fields we rely on.
- Open: Graphify's traversal ignores our access predicate (ADR-06) and tenant filter (ADR-10). Anything
  served from `graph.json` must be filtered by tenant and permission **before** export, never after. Until
  that is designed, exported graphs are for local, single-tenant, non-restricted data only.
- Open: licence. Sources disagree (Apache-2.0, MIT, or both files present). Legal review before acceptance.
- Open: whether the production graph store stays Neo4j with the Cypher templates, with Graphify used only for
  views and reports. Not decided here.

## Alternatives not evaluated

Writing our own graph viewer and traversal, or using Neo4j alone. Neither was prototyped, so this ADR makes
no claim about them beyond noting that they are the fallback if Graphify is rejected.

## Acceptance checklist

- [ ] Licence reviewed
- [ ] Tenant and access filtering design agreed (ADR-06, ADR-10)
- [ ] Pinned version and contract test in CI
- [ ] ARB approval
