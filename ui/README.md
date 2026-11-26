# USEP Console (UI)

React + TypeScript + Vite, with Cytoscape.js (MIT) for the graph. Flow: admin signs in, creates a configuration
(name and Git, Jira, Confluence, Figma URLs required; Active Directory URL optional), submits it for processing, selects it, and views its knowledge graph.

```bash
cd ui && npm install
npm run dev      # http://localhost:5173, mock API by default
npm test && npm run build
```

`.env.example`: `VITE_USE_MOCK=true` uses an in-browser mock with SYNTHETIC data (login `admin`/`admin`, dev only).
`VITE_USE_MOCK=false` calls `/api/*`, proxied to `VITE_API_TARGET`.

## API contract the UI expects (the API is built later; types in `src/api/types.ts`)

| Method and path | Body | Result |
|---|---|---|
| `POST /api/auth/login` | `{username, password}` | `{token, username}`; 401 on failure |
| `POST /api/auth/logout` | | 204 |
| `GET /api/configurations` | | `Configuration[]` for the caller's tenant only |
| `POST /api/configurations` | `{name, git_url, jira_url, confluence_url, figma_url, ad_url}` (`ad_url` optional: empty string = not set, stored as NULL; if given it may be `https://` or `ldaps://`; the rest are required, https only) | `Configuration` with `status: "processing"`; 422 `{message, fields:{<field>:<error>}}` |
| `GET /api/configurations/{id}` | | `Configuration`; 404 if not this tenant's |
| `GET /api/configurations/{id}/graph` | | `{configuration_id, generated_at, ontology_version, nodes[], edges[]}`; 409 until `status` is `ready` |

`status`: `submitted | processing | ready | failed` (+ optional `status_detail`). Nodes carry the canonical `concept`, extra
`labels`, `properties`, source and `confidence` (only when inferred). Edges carry the ontology `relation`, `confidence`
and `evidence_ref`. The graph endpoint must filter by tenant and permission before returning anything.

## Security notes
- The token is kept in memory only (reload signs out). The API must enforce auth, tenant isolation and URL validation; the UI checks
  (https only, no credentials in URLs, length limits) are for feedback, not control.
- Real login should be OIDC/SSO or a hardened session; the mock credentials must never be reused.
- Tenant definitions and configurations are stored in PostgreSQL: `services/ontology-registry/migrations/0001_*.sql`.

## Open points
- AD means Active Directory. Its URL may be `https://` (for example AD FS) or `ldaps://`; plain `ldap://` is refused. The AD URL is optional (nullable in the database); the other five are required.
- The graph shows stored facts only; ontology-definition and LLM-proposal views are not built.
