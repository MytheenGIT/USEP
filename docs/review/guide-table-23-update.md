# Replacement rows for Table 23 ("Design against repo") in USEP_Ontology_guide.docx

The Word file was not edited here (no editor available in this environment). Replace these rows by hand; checked against the repo on 27 Nov 2026.

| Item | In the repo today | Status |
|---|---|---|
| Query templates | 8 core YAML files plus 2 pack templates (`app_references_of`, `app_documents_of`, D2 awaiting acceptance). Pack CI and the golden-set check cover both. The context engine does not exist, so no template runs | Partly |
| Pack CI (C-07) | Local script `ontology/tools/check_ontology.py` (additive-only, policy tightening, templates including pack templates, shapes, every pack loads). No signing | Partly |
| Packs loaded at run time | One loader, `usep.ontology_runtime.load_ontology`, for the pipeline, labelling and the graph. Fails closed | Built |
| Schema gate G1 in ingest | Maps through the application pack, translates states through the project pack, checks required attributes and values. Quarantines as Q-SCHEMA or Q-STATE | Built |
| Connectors | Seven: Jira, GitLab, GitHub, Confluence, Figma, ServiceNow, ADO. Incremental, backfill, reconcile, webhooks. Not run against real systems | Built (unproven) |
| Runtime policy and onboarding | `config/runtime/*.yaml` and `config/sources.yaml` | Built |
| Registry (C-06), signing | Does not exist | Planned |

In short: definitions, local checks, one loader, gate G1, state translation, version pins, pack templates and the ingestion path are built. Signing, the registry, loading the edge rules from the organization pack, and everything after entity candidates (resolver, fabric writer, projectors, context engine) are still to build.
