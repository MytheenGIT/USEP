# Story template

Copy this into the Jira story (or the description of the story's pull request if Jira is not yet linked). Fill every field. A story with an empty field is not ready to start.

```
Story key:            USEP-___
Title:                <imperative summary>
Workstream:           W_ (see work-breakdown.md)
Component:            C-__ and folder under services/ or ontology/ or platform-iac/
HLD section:          HLD __._
LLD section:          LLD __._ (if any)
ADR:                  ADR-___ (or "none needed: reason")
Module:               1 to 8 (see architecture reference, section 2)
Owner (named):        <name>
CODEOWNERS role:      @usep/<role>

Inputs:               <data, events, config keys>
Outputs:              <tables, events, API responses>
Tables touched:       <list; tenant_id present in each>
Tokens and queries:   tenant_id carried; access predicate applied (yes/no; if no, why)
Audit events:         <event names emitted>
Ports and adapters:   <port names; adapter folders>
External calls:       <source, model, endpoint; approved endpoint for data class?>
Data class:           public / internal / restricted (embeddings and prompts are restricted)
Failure behaviour:    <fail closed; what the user sees>

Acceptance tests:     <test names and paths>
Golden set impact:    <none / which items; engineering-graded only in PoC>
Open items used:      O-__ (list, or none)

Definition of done:
- [ ] Code and tests merged through a pull request
- [ ] Checks in knowledge/04-development-standards.md section 7 pass
- [ ] Audit events verified in a test
- [ ] Build record written
- [ ] No secrets, no sensitive values in code, logs or fixtures
```
