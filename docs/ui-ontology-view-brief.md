# Brief for the UI team: show the ontology in the console

Status: proposal. The API does not exist yet; the UI builds against a fixture and the contract below.

## What the ontology is, in one paragraph
The ontology is the rulebook, not the data. It lists the kinds of thing that can exist (concepts such as Service, Team, Policy), the kinds of link between them (relationships such as `owns`), the allowed values, the named safe queries, and the rules that can only tighten access. It holds **no tenant data**. The existing graph view shows facts (real services and teams); this new view shows the definitions behind them. Read `ontology/README.md` and `USEP_Ontology_guide.docx` sections 1 to 4 first.

## What to build
A new tab, **Ontology**, next to "Knowledge graph" in `ui/src/App.tsx`, for the selected configuration. Five views:

| View | Shows | Notes |
|---|---|---|
| **Overview** | Core version, pack list (id, level, version, status, signed, reference-only), digest (first 12 characters, copy button) | Show a clear banner "Placeholder content" when any pack has `reference_only: true`. Show "Unsigned" when `signed` is false. Never present reference packs as real client content. |
| **Concepts** | A list grouped by `domain` (seven domains), searchable. A detail panel: description, parent, level and pack that defined it, attributes (name, type, required, multi, allowed values from `vocabularies[values_ref]`, and `defined_in` for inherited ones) | A pack concept shows its level and pack badge and its parent ("subclass of Control"). Do not let the user edit anything. |
| **Relationships** | A table: id, allowed "from" concepts, allowed "to" concepts, level, same-type flag. Click a concept chip to jump to it | Optional: a small Cytoscape diagram of concepts as nodes and relationships as edges (types only, not instances). Reuse `conceptColor` so colours match the graph view. |
| **Vocabularies** | Each controlled list and its values | Read only. |
| **Queries and policies** | Query templates (name, core or pack, max depth, fan-out cap) and policies (id, effect, level) | Effects are only `deny`, `require_approval`, `restrict_to_owners`. Show them as "tightens access"; never as grants. |

Cross-links worth adding: from a node in the graph view, a link "Concept: Service" that opens the concept's detail in the Ontology tab (the node's `concept` field is the key).

## Data contract
`GET /api/configurations/{id}/ontology`, tenant-scoped like the other endpoints (404 if not this tenant's, 401 without a token). It returns the ontology pinned for that configuration, so two tenants may see different packs. It is the same ontology that gate G1 enforces in the pipeline.

```ts
export interface OntologyDto {
  ontology_version: string;          // core version, e.g. "0.1.0"
  digest: string;                    // sha256 of every defining file; changes whenever any definition changes
  packs: { id: string; level: "core" | "industry" | "organization" | "application" | "project";
           version: string; status: string; signed: boolean; reference_only: boolean }[];
  domains: string[];
  concepts: {
    id: string; domain: string | null; level: string; pack_id: string; parent: string | null;
    description: string; role_only: boolean;       // role_only: recorded by role, never names or contact details
    attributes: { name: string; type: string; required: boolean; multi: boolean;
                  values_ref: string | null; defined_in: string }[];   // includes inherited attributes
  }[];
  relationships: { id: string; from: string[]; to: string[]; level: string; same_type: boolean }[];
  vocabularies: Record<string, string[]>;
  templates: { name: string; pack_id: string; max_depth: number; fanout_cap: number }[];   // pack_id "core" for core
  policies: { id: string; effect: "deny" | "require_approval" | "restrict_to_owners"; level: string }[];
  glossary: Record<string, string>;  // organisation word -> concept
}
```

- A **working fixture** is in `ui/src/api/fixtures/ontology.json` (18 concepts, 14 relationships, 10 templates; all packs are placeholders). Make `VITE_USE_MOCK=true` serve it. Add `getOntology(token, id)` to the `Api` interface in `src/api/types.ts` and implement it in `client.ts` and `mock.ts`.
- The backend builds the same JSON with `usep.ontology.export.to_dto`; a test keeps the fixture in step. If the contract needs a new field, ask the ontology owner and change the exporter, then regenerate with `python scripts/export_ontology_json.py ui/src/api/fixtures/ontology.json`.
- Data can be large (hundreds of concepts for a real tenant). Render lists with virtualisation or pagination; do not draw every relationship at once.

## Rules the UI must follow
1. **Read only.** No editing of core or pack definitions. Changes go through Git, pack CI and ARB review. If an "Edit" button is wanted later, it must open the change process, not write.
2. **Honest status.** Show `status`, `signed` and `reference_only` wherever a pack is named. Draft and reference content must look draft.
3. **No tenant data here.** The ontology endpoint holds none. Do not mix instance counts into it. If counts are wanted ("12 Services in this graph"), take them from the graph endpoint, already filtered by tenant and permission.
4. **Escape everything.** Descriptions and glossary words come from YAML files that tenants can influence at pack level. Render as text, never as HTML.
5. **Concept is canonical.** A custom label or glossary word never replaces the concept id. Where the glossary maps "Squad" to Team, show "Squad (Team)".
6. **Accessibility.** Colour must not be the only carrier of meaning (concept colours come with text labels, as in the graph view). Keyboard operation for list, detail panel and jump links.
7. **Tests.** Add Vitest tests for: the mock returns a valid `OntologyDto`; the banner appears for reference packs; an inherited attribute shows its `defined_in`; the concept jump from a graph node works.

## Not in scope yet
- Editing, proposing or approving ontology changes (needs the registry and pack signing, C-06 and C-07, which are not built).
- Showing LLM-proposed concepts or links (not built; `ui/README.md` lists this as an open point).
- Showing which pack-level changes are pending ARB approval. The review decisions are in `docs/review/`.

## Open points for the UI and ontology owners
- Which of the five views is first. Suggestion: Overview and Concepts, then Relationships.
- Whether the type-level diagram is wanted for the pilot or the table is enough.
- Where the tenant's pins come from. Until the registry exists the API reads them from configuration (`ontology.packs`).
