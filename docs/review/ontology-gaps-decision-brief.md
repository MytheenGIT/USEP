# Ontology gaps from the Git, Jira and Confluence design notes: decision brief

For the lead ontology engineer. Each item is a core change (HLD 6 Table 9 changes if accepted), so it needs ARB. Nothing here is built. All attributes and names are proposals (P). Related: OI-49, OI-58, OI-59.

| # | Gap | Why it matters | Options | Recommendation |
|---|---|---|---|---|
| G1 | **No link from a Change to the Service it modifies** (OI-59). `implements` only reaches a Requirement or Decision. | "Which services does this MR touch" and impact analysis cannot be answered. | (a) new core relationship `modifies` (Change to Service, API, DataAsset); (b) a derived rule from repository to Service; (c) leave it to a pack | (a). It is the most-asked traceability question, and the GitLab/GitHub/ADO repository maps to a Service already. |
| G2 | **No Sprint concept.** The notes use `IN_SPRINT` and `MERGED_IN`. | Delivery reporting by sprint is impossible. Jira sprint data is in the raw payload but unmapped. | (a) core concept; (b) application-pack concept (subclass of Release or a new type); (c) attribute `sprint` on Change | (c) for the pilot. A sprint is one tool's planning unit, so keep it out of the core, and revisit only if a second source needs it. |
| G3 | **No File concept.** The notes link a commit to the file paths it changes and a page to "payments/service.py". | File-level traceability and page-to-code links. | (a) core concept; (b) application-pack concept keyed by `repo:path`; (c) skip | (c) for v1, as the notes themselves advise. Metadata is in the raw diffs already. Revisit when a question needs it, as a pack concept (b). |
| G4 | **Confluence page hierarchy is normalized (`parent_id`) but has no relationship.** | Page trees show how documentation is organised, and ancestor pages scope the access check. | (a) a pack relationship `child_of` between Decision/page records; (b) keep it as an attribute only | (b). It adds an edge for no current query. Keep `parent_id` on the evidence record. |
| G5 | **No KPI concept** (OI-58). | The HLD 6.2 worked example ends at a KPI. | (a) core concept; (b) pack subclass | (b), an application or organization pack subclass. |
| G6 | **Pack-level query templates** (D2). **Built, awaiting acceptance.** | `references` and `documents` could not be queried. | (a) templates in the pack; (b) core templates that name pack relationships | (a), on four conditions, all enforced in code: golden items at every difficulty for each template (check_golden); names prefixed with the pack folder (`app_`); only pinned packs' templates load; and, when the context engine is built, its list of runnable templates must include them (a test to be added then). Pack CI applies the core's tenant, access, LIMIT, depth and fan-out rules. |
| G7 | **Person is role-only** (D3). | A person's GitLab user, Jira account and Confluence account cannot be linked, so person-centred questions fail. | (a) keep role-only; (b) a restricted identity alias table outside the ontology | Needs the security architect and data owner. It is not an ontology change if aliases live in the resolver, not the core. |

## Asks
- Decide G1, G2, G3 and G6 first. They change what the next mapping and shape work builds.
- G4 and G5 can wait for a question that needs them.
- G7 is a policy call with the security architect.
