# C-02 acquisition pipeline

Raw snapshot event in, ontology-valid entity candidates (or quarantine entries) out. No vendor SDK is imported here;
S3 and AWS Lambda sit in `usep/adapters/`.

```
usep/
  ports/            EventBus, ObjectStore (interfaces)
  adapters/s3/      S3EventBus (ADR-19), S3SnapshotStore
  adapters/aws_lambda/pipeline_handler.py   S3-notification and poll entry point
  ontology/         loader, bundle, gate G1 (map_record, validate)
  pipeline/
    worker.py       AcquisitionWorker: the flow below, publishing and writing evidence/quarantine
    normalize/      one module per source: parse(raw, ref) -> [Record]; registry in __init__.py
    redact.py       secrets and personal data masked before anything is stored
    classify.py     sensitivity 0..3, ACL state, owners-only
    mapping.py      application-pack mapping + project-pack state translation + gate
    state_tables.py which source field feeds which core attribute, and which workflow table translates it
    links.py        deterministic cross-system edges with method, confidence and evidence
    acl.py          merges the connector's harvested ACL with the parser's: principals, scopes, never loosens
    egress.py       may this text go to an external model? decided from labels, recorded on evidence
    topics.py       topic names and schemas
```

Flow per snapshot: `normalize` -> `redact` -> `classify` -> `mapping` (gate G1) -> evidence write -> publish
`entity.<domain>` (or `quarantine`) -> `links`. Each evidence object is also announced on `evidence.<family>` (contract: `docs/contracts/evidence.md`).

## Add a source
Connector side (`services/connectors`): `<source>/{client,models,connector,factory}.py`, a settings block in `config.py`,
the name in `registry.SOURCES`. Pipeline side: `normalize/<source>.py` and its entry in `normalize.PARSERS`, the family in
`topics.RAW_FAMILIES`, a mapping file in the application pack, and (if it has states) rows in `state_tables.py` plus the
tables in the project pack. The container, scheduler, API routes and Lambda handler read the registry and need no change.

## Tests
`tests/pipeline/` is one file per concern (`test_jira`, `test_git_sources`, `test_links`, ...) over shared helpers in
`helpers.py` and fixtures in `conftest.py`. Run from the repo root with `python -m pytest tests`.

## Checking edge precision
Link rules are trusted only after a human check (about 100 edges per relation type). Copy the bus locally
(`aws s3 sync s3://<bucket>/bus ./bus`), then:

```bash
python scripts/edge_precision.py sample ./bus edges_to_review.csv
python scripts/edge_precision.py score edges_reviewed.csv      # after filling the label column with y or n
```
The sample is repeatable and split across methods; the score is precision per relation and per relation and method (`precision.py`).

## From entity events to the graph
`usep.graph.entity_events.build_graph` turns `entity.*` events into a tenant graph (ends that match no single node are returned as
unresolved), and `write_graphify_restricted` exports only open, low-sensitivity nodes (ADR-19).
