# Build record template

One record per delivered change. Store it with the pull request, in `docs/builds/` (proposed folder; create it on first use).

```
Build record:         BR-<JIRA-KEY>-<yyyymmdd>
Story key:            USEP-___
Pull request:         <link>
Branch and commit:    <branch name>, <commit hash>
Date (UTC):           YYYY-MM-DDTHH:MM:SS.sssZ
Author:               <name>
Reviewer(s):          <CODEOWNERS roles and names>

Component and folder: C-__, services/<folder>/
Summary:              <what changed, one or two sentences>

Checks run:
- python ontology/tools/check_ontology.py       <pass/fail/not applicable>
- python -m pytest ontology/tests -q            <pass/fail/not applicable>
- python evals/tools/check_golden.py            <pass/fail/not applicable>
- python -m pytest evals/tests -q               <pass/fail/not applicable>
- Unit tests (service):                          <command and result>
- Integration tests (service):                   <command and result>

Audit events verified:  <event names; test that verified them>
Tenant isolation:       <test or query showing tenant_id present>
Golden set impact:      <none, or result labelled engineering-graded>
ADR references:         <ADR numbers>
Deviations introduced:  <none, or ADR number and exit criterion>
Known gaps:             <what is not done and why>
Follow-ups:             <Jira keys>
Evidence location:      <path or link to logs or screenshots; no secrets or customer data>
```
