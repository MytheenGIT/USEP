# Decision note for the ontology owner and the architecture board

One page. Each row needs a yes, a no, or a change. Details: `ontology-owner-review.md`, `ontology-gaps-decision-brief.md`.
Nothing here is signed or published. Until answered, the item stays a proposal.

| # | Decision | What we recommend | If you say no | Who decides |
|---|---|---|---|---|
| 1 | **D2** Let packs carry their own query templates (`references_of`, `documents_of` are built) | Yes. Names start with the pack folder; same safety rules as core; golden items at every difficulty | `references` and `documents` stay unqueryable, or the core gets templates that name a pack's links | Lead ontology engineer, ARB |
| 2 | **OI-59** Add a core relationship `modifies` (Change to Service, API, DataAsset) | Yes | "Which services does this change touch" has no answer; impact analysis loses its main hop | Lead ontology engineer |
| 3 | **Sprint** | Attribute on Change for the pilot, not a core concept | Core concept (more work, ties the core to one tool's planning unit) | Lead ontology engineer |
| 4 | **File** (changed-file lists) | Skip for v1; revisit as a pack concept | Pack concept keyed by `repo:path` | Lead ontology engineer |
| 5 | **Confluence page hierarchy** (`CHILD_OF`) | Keep `parent_id` as an attribute; no edge | Pack relationship `child_of` | Lead ontology engineer |
| 6 | **KPI** concept | Pack subclass | Core concept | Lead ontology engineer |
| 7 | **Precedence** (which source wins per attribute, ADR-17) | Hold the week-4 workshop; until then conflicts stay open | Name a default order now (risk: silent wrong winners) | ARB, enterprise architect |
| 8 | **D3** Person stays role-only; where identity aliases live | Keep role-only; aliases live in the resolver, outside the ontology | Add names and emails to the core (privacy review needed) | Security architect, data owner |
| 9 | **D8** What may go to external models | Keep the strict default; relax per source once ACLs are harvested | Relax now (most records are owners-only today) | Security architect, data owners |
| 10 | **D1, D4, D5, D6** | Keep `references`/`documents` in the pack; one `git` source value; source-id formats as listed; `references` for MR to Jira Task or Bug | Promote to core (D1), split `git` into three (D4) | Lead ontology engineer, platform engineer |
| 11 | **Signing and the registry** (C-06, C-07): which key service signs packs, where the registry runs | Choose before building: nothing can be signed meaningfully without it | Packs stay unsigned; services keep loading from Git | Platform lead, security architect |
| 12 | **ADR-19** (S3 events + SQS instead of Kafka; Graphify as view layer) | Accept ADR-19 (event bus); Graphify after licence review | Revisit the bus choice | ARB |
| 13 | **Pilot scope for connectors**: webhooks (now built, secrets needed) and Git clone/fetch (not built) | Webhooks yes; REST-only for Git in the pilot | Ask for clone/fetch: a separate piece of work (storage, git in Lambda) | Delivery lead, platform lead |
| 14 | **Real pack content and named owners** | Start with the application and project packs (smallest, most concrete) | Packs stay samples | Industry, application and delivery leads |
