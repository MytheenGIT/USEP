# USEP Console (UI)

React 18 + TypeScript + Vite, with Cytoscape.js (MIT) for the graph. No UI framework or router dependency: a few shared components, a hash router and CSS design tokens (light, dark, or follow the system).

Flow: the admin signs in and fills in a configuration. There are no steps: six connector tabs (Jira, Confluence, GitLab, GitHub, ServiceNow, Figma) sit side by side and open in any order. **No connector is mandatory**: each tab has a "Use <connector>" switch, off by default, and only the connectors that are on are checked, sent and read (at least one must be on). Each takes what it needs, with its token (a password for ServiceNow) in a field with an eye inside it:

- **Jira**: any number of project keys, and/or its own JQL queries.
- **Confluence**: any number of space keys or space links.
- **GitLab and GitHub**: sign in with a token or an SSH key. Add repositories as round chips (a name, a link or an SSH link), or open **Choose from my repositories** to search the list the token can reach and tick several at once, or switch on every repository the account can reach.
- **ServiceNow**: instance, username, password, tables (with one-click suggestions) and an optional filter.
- **Figma**: any number of files (blocked until the DPIA is signed off).

A configuration that is ready can take more connectors later: **Add a connector** on its page opens the same form with only the connectors it does not use yet. The earlier ones are kept and not read again (so their tokens are not needed), only the new ones are read, and the graph is rebuilt with everything.

One button, **Connect and create**, checks every connection by itself (there is no test button; only a problem is shown), creates the configuration, and opens a processing page with a spinner and what each source is doing. When it is ready the **knowledge graph** opens by itself. From the graph, **Ask the agent** opens a chat about it (a mock-up, see below). The left panel lists Configurations, Knowledge graphs and Ask the agent, with the signed-in admin, a profile page and Sign out at the bottom.

## Showcase mode (no accounts needed)

```bash
cd ui && npm install && npm run demo      # http://localhost:5173, login admin / admin
```

`npm run demo` swaps the API for an in-browser mock with SYNTHETIC data, so the whole flow can be shown without access to any real Jira, Confluence, GitLab, GitHub, ServiceNow or Figma. Nothing leaves the browser. It starts with two finished configurations (one with all six connectors) so the knowledge graph and the agent have something to show; a new configuration is "read" in a few seconds, with the processing page, and opens its graph. The graph grows with the connectors switched on (Jira adds requirements, GitLab and GitHub add changes, ServiceNow adds incidents and change requests, Confluence adds decisions, Figma adds designs). The mock lists 12 repositories to choose from. A token containing the word "bad" fails the connection check, to show the error. The agent is a preview: it answers a few kinds of question (overview, requirements without a change, incidents and their causes, owners, recent changes) from the graph on screen, and cites the nodes it used. It is not a language model.

```bash
# 1. backend (services/connectors): set admin credentials in services/connectors/.env, then
cd services/connectors && .venv/bin/uvicorn main:app --port 8000

# 2. UI
cd ui && npm install
npm run dev          # http://localhost:5173, calls the real API (proxy /api -> VITE_API_TARGET)
npm run demo         # the same UI on the in-browser mock: no backend, no accounts
npm test && npm run build
```

`.env.example`: `VITE_API_TARGET` is the backend (default `http://localhost:8000`). `VITE_USE_MOCK=true` swaps in an in-browser mock with SYNTHETIC data (login `admin`/`admin`, development only) for working without a backend.

## Logos and profile menu

The logos are in `ui/public/brand/` (`ust-logo.png`, `kf-logo.png`), both with transparent backgrounds so they can follow the theme:

| File | Where it appears | How it adapts to light and dark |
|---|---|---|
| `ust-logo.png` | small, beside "Universal Semantic Engineering Platform" at the top of the sidebar (and alone in the collapsed rail) | black glyphs on transparent; dark mode inverts it to white (`--logo-filter`) |
| `kf-logo.png` | round profile-style badge in the top bar next to the user name | colour logo on a round badge whose backing is white in light mode and a soft light tone in dark mode (`--avatar-bg`) |

The sign-in page has no logos. Clicking the KF badge or the user name opens the account menu: name and role, a System / Light / Dark theme switch, and Sign out.

### Connector logos

`ui/public/brand/connectors/{jira,confluence,gitlab,figma}.svg` show on the connector tabs and panels, the list and the detail page. Each is shown on a white tile
so its brand colour is right in light and dark mode, and a missing file falls back to the first letter. The four files are single-path vector icons from the
Simple Icons package (`simple-icons@13.21.0` on npm, icon files under CC0), each given its brand colour. The names and marks belong to their owners (Atlassian,
GitLab, Figma); they are used here only to identify the connector for that product.

### Replacing the UST or KF logo

To replace a logo, overwrite the file (an `.svg` with the same base name is used first if present). For UST use dark glyphs on a transparent background so the dark-mode
inversion works; for KF use any colour logo on transparent. Until a file exists, the text "UST" or "KF" is shown. After adding a new file to a running dev server,
reload the page once. These files are served publicly with the app, so only keep logos you are allowed to use.

This console is built for laptop and desktop browsers (about 1024px wide and up); there is no phone layout.

## Structure

```
src/
  app/          App, AppShell, Sidebar (collapsible), hash router, theme
  shared/
    api/        types.ts (the contract), connectors.ts (connector facts), http.ts, mock.ts, client.ts
    ui/         Button, Badge, Card, Field, SecretField, TagInput, Switch, Icon, Toast, feedback components
    hooks/      useAsync, usePolling
    lib/        configValidation (shared rules), format
  features/
    agent/           AgentPage (chat mock-up) and answer.ts (answers from the graph, tested)
    auth/            AuthContext (in-memory session), LoginPage
    configurations/  ConfigurationsContext, list, detail, NewConfigurationPage, formModel,
                     connectors/ (definitions.ts, ConnectorStepper, ConnectorPanel)
    graph/           page, canvas (Cytoscape), filters, node details, table view, graphModel
  styles/       tokens, base, components, layout
```

**Adding a connector:** (it is optional like the others: add a switch-able card, and the server rules in `console_api/validation.py`) add its facts to `shared/api/connectors.ts` (and the backend `SPECS` in `console_api/validation.py`), then describe its
card in `features/configurations/connectors/definitions.ts`. The form, validation and payload are generated from those.

The graph page is lazy-loaded so Cytoscape stays out of the first bundle. To add a page: a route in `app/router.tsx`, a folder under `features/`, a case in `app/App.tsx`.

## API contract (served by `services/connectors/console_api`; types in `src/shared/api/types.ts`)

| Method and path | Result |
|---|---|
| `POST /api/auth/login`, `POST /api/auth/logout` | session token (401 on failure, 429 when throttled); 204 |
| `GET /api/connector-defaults` | per connector: server base URL, whether the server holds credentials, `blocked_reason` (Figma until the DPIA is signed off), and `ssh_available` (GitHub and GitLab: whether the server can read over SSH) |
| `POST /api/connectors/{jira,confluence,gitlab,github,servicenow,figma}/test` | `{ok, message}` or 422 with field errors. The form calls it by itself when a configuration is created |
| `POST /api/connectors/{github,gitlab}/repositories` | `{repositories: [{path, name, visibility}], truncated}`: what the token can reach, for choosing from; 422 with a message if it cannot be listed |
| `GET /api/configurations`, `GET /api/configurations/{id}` | `Configuration` with `connectors` summary and `sources[]` |
| `POST /api/configurations/{id}/connectors` | body `{connectors: {...}}` with only the new connectors; returns the configuration as `processing`. 422 if one is already in it, 409 if it is not ready |
| `POST /api/configurations` | body `{name, connectors: {jira?, confluence?, gitlab?, figma?}}`, each used connector with `enabled: true` (Jira: `project_keys`, `jql_queries`. GitLab: `project_paths`, `all_member_projects`, `auth_method`, `ssh_key`. GitHub: `repositories`, same options. ServiceNow: `email` is the username, `api_token` the password, `tables`, `encoded_query`); 201 or 422 with `fields` keyed `name`, `connectors`, `<connector>.<field>` |
| `GET /api/configurations/{id}/graph` | graph; 409 until `status` is `ready` |

The connector fields and the rules for secrets and typed hosts are in `services/connectors/README.md`. `status`: `submitted | processing | ready | failed`. `ready` means every connector that was switched on was read; a failed selected source makes the configuration `failed` with no graph. A connector that was not switched on is not part of the configuration.
Errors: `{code, message, trace_id, fields?}`.

## Security notes
- The token is kept in memory only (a reload signs out). Only the theme choice is stored in the browser. The API enforces auth, tenant isolation and URL validation; the UI checks (https only, no credentials in URLs, length limits) are for feedback, not control.
- Tokens typed into the form are write-only: sent over the API for one run, never stored, returned or logged; the form is cleared after submit. The server guards typed hosts (https only, no private addresses unless allowed).
- Real login should be OIDC/SSO; the mock credentials must never be reused.

## Open points
- Active Directory was removed from the form: there is no AD connector yet. Add a card when one exists.
- Tokens are held in server memory for one run. A Vault-backed credential design (proposed ADR-036) replaces that.
- The graph is a provisional projection of fetched data. Ontology-definition and LLM-proposal views are not built.
