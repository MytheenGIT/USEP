# C-02 acquisition pipeline

Raw snapshot event in, ontology-valid entity candidates (or quarantine entries) out. No vendor SDK is imported here;
S3 and AWS Lambda sit in `usep/adapters/`.

```
usep/
  ports/            EventBus, ObjectStore (interfaces)
  adapters/s3/      S3EventBus (ADR-19), S3ObjectStore
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
    topics.py       topic names and schemas
```

Flow per snapshot: `normalize` -> `redact` -> `classify` -> `mapping` (gate G1) -> evidence write -> publish
`entity.<domain>` (or `quarantine`) -> `links`.

## Add a source
Connector side (`services/connectors`): `<source>/{client,models,connector,factory}.py`, a settings block in `config.py`,
the name in `registry.SOURCES`. Pipeline side: `normalize/<source>.py` and its entry in `normalize.PARSERS`, the family in
`topics.RAW_FAMILIES`, a mapping file in the application pack, and (if it has states) rows in `state_tables.py` plus the
tables in the project pack. The container, scheduler, API routes and Lambda handler read the registry and need no change.

## Tests
`tests/pipeline/` is one file per concern (`test_jira`, `test_git_sources`, `test_links`, ...) over shared helpers in
`helpers.py` and fixtures in `conftest.py`. Run from the repo root with `python -m pytest tests`.
