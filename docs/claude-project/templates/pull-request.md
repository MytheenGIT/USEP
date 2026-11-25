# Pull request template

Paste this into the pull request description. Fill every line. Delete a line only when it does not apply, and say why.

```
## Story
<JIRA-KEY> <title>. Component C-__. HLD section __. ADR-___.

## What changed
<two to four sentences; name the folder under services/, ontology/, platform-iac/ or docs/>

## Why
<the requirement, the story or the ADR that requires it>

## Tests and checks
- [ ] python ontology/tools/check_ontology.py
- [ ] python -m pytest ontology/tests -q
- [ ] python evals/tools/check_golden.py
- [ ] python -m pytest evals/tests -q
- [ ] Unit and integration tests for this service: <commands>

## Standards check
- [ ] tenant_id in every token and query
- [ ] Audit event emitted for every read, write, external call and model call
- [ ] Only the fabric writer inserts facts; only action adapters write to sources
- [ ] Vendor SDKs only inside adapters
- [ ] No secrets, prompts, source content or sensitive personal values in code, logs or fixtures
- [ ] UUID v7 IDs and UTC ISO 8601 timestamps
- [ ] Fails closed on any check or dependency failure
- [ ] Retrieval scores described as retrieval relevance

## Review
- CODEOWNERS roles requested: @usep/<role>
- Deviations introduced: none / ADR-___ with exit criterion

## Build record
Link: <path or link to BR-...>

## Known gaps
<what is not done, and why>
```
