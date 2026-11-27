// DEV-ONLY in-memory API with SYNTHETIC data, for working on or showing the UI without a backend (VITE_USE_MOCK=true, or
// `npm run demo`). It is not a security control: the credentials below are a development convenience and must never be reused.
// Everything here is invented: no real Jira, Confluence, GitLab, GitHub, ServiceNow or Figma is contacted.
import { CONNECTOR_KEYS, CONNECTOR_META } from "./connectors";
import { validateConfigInput } from "../lib/configValidation";
import graphifyFixture from "./fixtures/ontology.graphify.json";
import ontologyFixture from "./fixtures/ontology.json";
import {
  Api, ApiError, ConfigInput, Configuration, ConnectorDefault, ConnectorKey, ConnectorSummary, GraphDto, GraphEdgeDto, GraphNodeDto, GraphifyGraph, OntologyDto,
  RepositoryChoice,
} from "./types";

/** The ontology the demo configurations were "checked against": the real reference-pack ontology (the fixture). */
function pinned(c: Configuration): Configuration {
  const o = ontologyFixture as unknown as OntologyDto;
  c.ontology = { version: o.ontology_version, digest: o.digest, packs: o.packs.map((p) => `${p.id}@${p.version}`), reference_only: o.packs.some((p) => p.reference_only), checked_at: new Date().toISOString(), nodes_dropped: 0, edges_dropped: 0 };
  return c;
}

export const MOCK_USER = "admin";
export const MOCK_PASSWORD = "admin";
/** How long a source "takes to read" in the demo, so the processing page can be shown. */
export const STEP_MS = 1400;

const configs: Configuration[] = [];
const sessions = new Set<string>();

function auth(token: string) {
  if (!sessions.has(token)) throw new ApiError(401, "Not signed in");
}
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------------------------------------------------
// The knowledge graph. The architecture part is the demo graph the project started with (teams, services, APIs, data,
// capabilities, policies). Each connector adds what that source would contribute, so the graph follows the connectors.
// ---------------------------------------------------------------------------------------------------------------------

type Has = Record<ConnectorKey, boolean>;

function demoGraph(c: Configuration): GraphDto {
  const has = Object.fromEntries(CONNECTOR_KEYS.map((k) => [k, !!c.connectors[k]?.enabled])) as Has;
  const code = has.gitlab ? "gitlab" : has.github ? "github" : "architecture";
  const nodes: GraphNodeDto[] = [];
  const edges: GraphEdgeDto[] = [];
  const n = (id: string, concept: string, name: string, extra: Partial<GraphNodeDto> = {}) =>
    nodes.push({ id, concept, name, labels: [], properties: {}, source_system: "architecture", ontology_version: "0.1.0", ...extra });
  const e = (s: string, relation: string, t: string, confidence = 1, source_system = "architecture") =>
    edges.push({ id: `${s}-${relation}-${t}`, source: s, target: t, relation, confidence, source_system, evidence_ref: `demo:${s}:${t}` });

  // architecture: what the platform is made of
  n("team-pay", "Team", "payments-team", { labels: ["Squad"], properties: { members: 7 } });
  n("team-plat", "Team", "platform-team", { labels: ["Squad"], properties: { members: 5 } });
  n("svc-checkout", "Service", "checkout-service", { labels: ["architecture"], source_system: code, properties: { criticality: "tier_1", lifecycle_state: "active", repository_ref: "checkout-service" } });
  n("svc-billing", "Service", "billing-service", { labels: ["architecture"], source_system: code, properties: { criticality: "tier_1", lifecycle_state: "active" } });
  n("svc-notify", "Service", "notification-service", { labels: ["architecture"], source_system: code, properties: { criticality: "tier_3", lifecycle_state: "active" } });
  n("api-checkout", "API", "checkout-api", { properties: { protocol: "rest", version: "v2" } });
  n("api-billing", "API", "billing-api", { properties: { protocol: "rest", version: "v1" } });
  n("data-orders", "DataAsset", "orders-db", { properties: { regulatory_scope: ["pci_dss"] } });
  n("data-ledger", "DataAsset", "ledger-db", { properties: { regulatory_scope: ["pci_dss", "sox"] } });
  n("env-prod", "Environment", "production", { properties: { environment_kind: "production" } });
  n("env-stage", "Environment", "staging", { properties: { environment_kind: "pre_production" } });
  n("cap-pay", "Capability", "Payments", { source_system: has.confluence ? "confluence" : "architecture" });
  n("cap-invoice", "Capability", "Invoicing", { source_system: has.confluence ? "confluence" : "architecture" });
  n("pol-change", "Policy", "Change control", { source_system: has.confluence ? "confluence" : "architecture" });
  n("pol-pci", "Policy", "PCI DSS controls", { source_system: has.confluence ? "confluence" : "architecture" });
  n("test-contract", "Test", "checkout contract tests", { source_system: code, properties: { test_kind: "contract" } });
  for (const [s, t] of [["team-pay", "svc-checkout"], ["team-pay", "svc-billing"], ["team-plat", "svc-notify"]]) e(s, "owns", t);
  e("svc-checkout", "exposes", "api-checkout"); e("svc-billing", "exposes", "api-billing");
  e("svc-checkout", "consumes", "data-orders"); e("svc-billing", "consumes", "data-ledger"); e("svc-checkout", "consumes", "api-billing");
  e("svc-checkout", "realizes", "cap-pay", 0.8); e("svc-billing", "realizes", "cap-invoice", 0.8);
  for (const s of ["svc-checkout", "svc-billing", "svc-notify"]) e(s, "deployed_to", "env-prod");
  e("svc-checkout", "deployed_to", "env-stage"); e("svc-checkout", "governed_by", "pol-change"); e("svc-billing", "governed_by", "pol-pci");
  e("test-contract", "tests", "svc-checkout");

  // Jira: requirements, and a bug that looks like an incident
  if (has.jira) {
    n("req-12", "Requirement", "PAY-12 Retry failed payments", { source_system: "jira", properties: { status: "Done", priority: "High" } });
    n("req-18", "Requirement", "PAY-18 Email receipts", { source_system: "jira", properties: { status: "In Progress", priority: "Medium" } });
    n("req-23", "Requirement", "PAY-23 Partial refunds", { source_system: "jira", properties: { status: "To Do", priority: "Medium" } });
    n("req-31", "Requirement", "PAY-31 3-D Secure support", { source_system: "jira", properties: { status: "Done", priority: "High" } });
    n("bug-40", "Incident", "PAY-40 Double charge on retry", { source_system: "jira", labels: ["Bug"], confidence: 0.6, properties: { severity: "sev2" } });
    // (no "realizes" from a service to a requirement: the ontology only lets a service realize a capability)
  }

  // GitLab / GitHub: code changes that implement the requirements
  const change = (id: string, system: string, name: string, state: string) => n(id, "Change", name, { source_system: system, labels: [system === "github" ? "pull_request" : "merge_request"], properties: { change_state: state } });
  if (has.gitlab) {
    change("chg-gl-7", "gitlab", "MR 7 Add retry with backoff", "released");
    change("chg-gl-9", "gitlab", "MR 9 3-D Secure challenge flow", "released");
    // No "modifies" edge to the service: the ontology has no Change -> Service relationship, so the real graph would drop it.
    if (has.jira) { e("chg-gl-7", "implements", "req-12", 1, "gitlab"); e("chg-gl-9", "implements", "req-31", 1, "gitlab"); }
    if (has.jira) e("bug-40", "caused_by", "chg-gl-7", 0.6, "gitlab");
  }
  if (has.github) {
    change("chg-gh-112", "github", "PR 112 Receipt email template", "in_review");
    change("chg-gh-118", "github", "PR 118 Refund endpoint", "open");
    if (has.jira) { e("chg-gh-112", "implements", "req-18", 1, "github"); e("chg-gh-118", "implements", "req-23", 1, "github"); }
  }

  // ServiceNow: operations records
  if (has.servicenow) {
    n("chg-sn-1001", "Change", "CHG0001001 Deploy retry logic to production", { source_system: "servicenow", labels: ["change_request"], properties: { change_state: "closed" } });
    n("inc-7001", "Incident", "INC0007001 Checkout timeouts after release", { source_system: "servicenow", labels: ["incident"], confidence: 0.6, properties: { priority: "1 - Critical", group: "Payments Support" } });
    n("inc-7002", "Incident", "INC0007002 Duplicate receipts sent", { source_system: "servicenow", labels: ["incident"], confidence: 0.6, properties: { priority: "3 - Moderate", group: "Platform Support" } });
    e("inc-7001", "caused_by", "chg-sn-1001", 0.6, "servicenow"); 
    if (has.jira) e("chg-sn-1001", "implements", "req-12", 1, "servicenow");
  }

  // Confluence: decisions and the policies they refer to
  if (has.confluence) {
    n("adr-14", "Decision", "ADR-014 Use idempotency keys for payments", { source_system: "confluence", labels: ["adr"], confidence: 0.6 });
    n("adr-21", "Decision", "ADR-021 Send receipts asynchronously", { source_system: "confluence", labels: ["adr"], confidence: 0.6 });
    e("svc-checkout", "decided_in", "adr-14", 0.8, "confluence"); e("svc-notify", "decided_in", "adr-21", 0.8, "confluence");
    if (has.jira) e("adr-14", "references", "req-12", 0.6, "confluence");
  }

  // Figma: the designs that specify the flows
  if (has.figma) {
    n("dsg-checkout", "Capability", "Checkout flow (design)", { source_system: "figma", labels: ["design"], properties: { frames: 14 } });
    n("dsg-receipt", "Capability", "Receipt email (design)", { source_system: "figma", labels: ["design"], properties: { frames: 4 } });
    e("svc-checkout", "realizes", "dsg-checkout", 0.7, "figma"); e("svc-notify", "realizes", "dsg-receipt", 0.7, "figma");
  }

  return { configuration_id: c.id, generated_at: new Date().toISOString(), ontology_version: "0.1.0", ontology_digest: (ontologyFixture as unknown as OntologyDto).digest, nodes, edges };
}

// ---------------------------------------------------------------------------------------------------------------------

// Mirrors console_api/validation.py's FIGMA_DPIA_MESSAGE: the real server blocks Figma until the DPIA is signed off.
const FIGMA_DPIA_MESSAGE = "Figma cannot be used until the DPIA is signed off (ADR-025). Ask the operator to record the approval.";

const DEFAULTS: Record<string, ConnectorDefault> = {
  ado: { base_url: null, credentials_configured: false, blocked_reason: null, ssh_available: false },
  jira: { base_url: null, credentials_configured: false, blocked_reason: null, ssh_available: false },
  confluence: { base_url: null, credentials_configured: false, blocked_reason: null, ssh_available: false },
  gitlab: { base_url: "https://gitlab.com", credentials_configured: true, blocked_reason: null, ssh_available: true },
  github: { base_url: "https://api.github.com", credentials_configured: false, blocked_reason: null, ssh_available: true },
  servicenow: { base_url: null, credentials_configured: false, blocked_reason: null, ssh_available: false },
  figma: { base_url: null, credentials_configured: false, blocked_reason: FIGMA_DPIA_MESSAGE, ssh_available: false },
};

const GITHUB_REPOS: RepositoryChoice[] = [
  ["acme/checkout-service", "private", "Checkout API and payment orchestration"], ["acme/billing-service", "private", "Invoices and ledger postings"],
  ["acme/notification-service", "private", "Email and push notifications"], ["acme/web-app", "private", "Customer web application"],
  ["acme/mobile-app", "private", "iOS and Android clients"], ["acme/payments-sdk", "public", "Open-source client SDK"],
  ["acme/infra-terraform", "private", "Cloud infrastructure as code"], ["acme/data-platform", "private", "Pipelines and warehouse models"],
  ["acme/design-system", "public", "Shared UI components"], ["acme/fraud-rules", "private", "Rules for the fraud engine"],
  ["acme/ledger", "private", "Double-entry ledger library"], ["acme/docs", "public", "Developer documentation"],
].map(([path, visibility, description]) => ({ path, name: path.split("/")[1], visibility, description }));

const GITLAB_REPOS: RepositoryChoice[] = [
  ["payments/checkout", "private", "Checkout API"], ["payments/billing", "private", "Billing"], ["payments/notifications", "internal", "Notifications"],
  ["platform/infra", "private", "Infrastructure"], ["platform/observability", "internal", "Dashboards and alerts"], ["platform/ci-templates", "internal", "Shared pipelines"],
  ["mobile/ios-app", "private", "iOS"], ["mobile/android-app", "private", "Android"], ["data/etl", "private", "ETL jobs"], ["data/warehouse-models", "private", "Models"],
].map(([path, visibility, description]) => ({ path, name: path.split("/")[1], visibility, description }));

function summarise(input: ConfigInput): Configuration["connectors"] {
  return Object.fromEntries(CONNECTOR_KEYS.map((k) => {
    const c = input.connectors[k];
    const meta = CONNECTOR_META[k];
    const on = c?.enabled === true;
    const ssh = on && meta.supportsSsh && c?.auth_method === "ssh_key";
    const rawTargets = on && c ? ((c as unknown as Record<string, unknown>)[meta.targetField] ?? []) : [];
    const targetStrings = Array.isArray(rawTargets) ? rawTargets.map((t: unknown) => String(t ?? "").replace(/^git@[^:]+:/, "").replace(/\.git$/, "")) : [];
    return [k, {
      enabled: on,
      base_url: on && meta.needsBaseUrl && c ? (c.base_url?.trim() || DEFAULTS[k].base_url) : null,
      email: on && meta.needsEmail && c && !c.use_server_credentials ? c.email?.trim() ?? null : null,
      targets: on ? [...new Set(targetStrings)] : [],
      jql_queries: on && k === "jira" && c ? [...new Set((c.jql_queries ?? []).map((q) => q.trim()).filter(Boolean))] : [],
      all_member_projects: on && c && meta.alternative === "all_member_projects" && c.all_member_projects === true && !ssh,
      auth_method: ssh ? "ssh_key" : "token",
      encoded_query: on && k === "servicenow" && c ? c.encoded_query?.trim() ?? "" : "",
      credentials: !on ? "none" : c?.use_server_credentials ? "server" : "provided",
    } satisfies ConnectorSummary];
  })) as Configuration["connectors"];
}

const DOCS: Record<ConnectorKey, number> = { ado: 45, jira: 124, confluence: 58, gitlab: 63, github: 41, servicenow: 37, figma: 9 };

/** A configuration that is already read, so a demo opens on something to look at. */
function seed(name: string, hoursAgo: number, input: ConfigInput) {
  const c: Configuration = {
    id: crypto.randomUUID(), name, connectors: summarise(input), status: "ready",
    created_at: new Date(Date.now() - hoursAgo * 3_600_000).toISOString(), created_by: MOCK_USER,
    sources: CONNECTOR_KEYS.filter((k) => input.connectors[k]?.enabled).map((k) => ({ source: k, state: "success" as const, documents_count: DOCS[k] })),
  };
  configs.push(pinned(c));
}

const on = (extra: Partial<NonNullable<ConfigInput["connectors"][ConnectorKey]>> = {}) => ({ enabled: true, use_server_credentials: false, ...extra });
seed("Payments platform (demo)", 3, {
  name: "Payments platform (demo)",
  connectors: {
    jira: on({ base_url: "https://acme.atlassian.net", email: "dev@acme.test", project_keys: ["PAY", "OPS"], jql_queries: ["labels = release AND status != Closed"] }),
    confluence: on({ base_url: "https://acme.atlassian.net", email: "dev@acme.test", space_keys: ["ENG", "PAY", "ARCH"] }),
    gitlab: on({ base_url: "https://gitlab.com", use_server_credentials: true, project_paths: ["payments/checkout", "payments/billing"], all_member_projects: false }),
    github: on({ base_url: "https://api.github.com", repositories: ["acme/notification-service", "acme/web-app"], all_member_projects: false }),
    servicenow: on({ base_url: "https://acme.service-now.com", email: "svc-ingest", tables: ["incident", "change_request"] }),
    figma: on({ file_keys: ["AbCdEf1234567890"] }),
  },
});
seed("Checkout team (Jira and GitLab)", 26, {
  name: "Checkout team (Jira and GitLab)",
  connectors: { jira: on({ base_url: "https://acme.atlassian.net", email: "dev@acme.test", project_keys: ["PAY"] }), gitlab: on({ use_server_credentials: true, all_member_projects: true }) },
});

export const mockApi: Api = {
  async login(username, password) {
    if (username !== MOCK_USER || password !== MOCK_PASSWORD) throw new ApiError(401, "Invalid username or password");
    const token = crypto.randomUUID();
    sessions.add(token);
    return { token, username };
  },
  async logout(token) { sessions.delete(token); },
  async connectorDefaults(token) { auth(token); return DEFAULTS; },
  async testConnector(token, key, input) {
    auth(token);
    await wait(700);
    const meta = CONNECTOR_META[key];
    if (input.auth_method !== "ssh_key" && (input.api_token ?? "").toLowerCase().includes("bad")) {
      return { ok: false, message: `${meta.label}: cannot sign in: HTTP 401: Bad credentials` };
    }
    const targetArray = ((input as unknown as Record<string, unknown>)[meta.targetField] ?? []) as unknown[];
    const targetCount = Array.isArray(targetArray) ? targetArray.length : 0;
    const n = targetCount + (input.jql_queries ?? []).filter((q) => q.trim()).length;
    return { ok: true, message: `Connected${n ? `. ${n} ${meta.targetLabel.toLowerCase()} reachable` : ""}${input.all_member_projects ? ". 12 more found from membership" : ""}` };
  },
  async listRepositories(token, key, input) {
    auth(token);
    if (key !== "github" && key !== "gitlab") throw new ApiError(404, "That connector has no repositories to choose from");
    if (input.auth_method === "ssh_key") throw new ApiError(422, "Choosing from your repositories needs a token: an SSH key cannot list them", undefined, "repositories_unavailable");
    if (!input.use_server_credentials && !(input.api_token ?? "").trim()) throw new ApiError(422, `Enter the ${CONNECTOR_META[key].label} token first`, undefined, "repositories_unavailable");
    await wait(600);
    if ((input.api_token ?? "").toLowerCase().includes("bad")) throw new ApiError(422, "Could not list repositories: HTTP 401: Bad credentials", undefined, "repositories_unavailable");
    return { repositories: key === "github" ? GITHUB_REPOS : GITLAB_REPOS, truncated: false };
  },
  async listConfigurations(token) { auth(token); return [...configs].sort((a, b) => b.created_at.localeCompare(a.created_at)).map((c) => ({ ...c })); },
  async createConfiguration(token, input) {
    auth(token);
    const errors = validateConfigInput(input, DEFAULTS);
    if (Object.keys(errors).length) throw new ApiError(422, "Check the highlighted fields", errors);
    const c: Configuration = {
      id: crypto.randomUUID(), name: input.name.trim(), connectors: summarise(input), status: "processing",
      created_at: new Date().toISOString(), created_by: MOCK_USER, sources: [],
    };
    configs.unshift(c);
    const keys = CONNECTOR_KEYS.filter((k) => c.connectors[k].enabled);
    keys.forEach((k, i) => setTimeout(() => {
      c.sources = [...(c.sources ?? []), { source: k, state: "success", documents_count: DOCS[k] }];
    }, STEP_MS * (i + 1)));
    setTimeout(() => { c.status = "ready"; pinned(c); }, STEP_MS * (keys.length + 1));
    return { ...c };
  },
  async addConnectors(token, id, connectors) {
    auth(token);
    const c = configs.find((x) => x.id === id);
    if (!c) throw new ApiError(404, "Configuration not found");
    if (c.status !== "ready") throw new ApiError(409, "A connector can be added once the configuration is ready. Use Edit and resubmit instead.", undefined, "not_ready");
    const wanted = CONNECTOR_KEYS.filter((k) => connectors[k]?.enabled === true);
    const already = wanted.filter((k) => c.connectors[k]?.enabled).map((k) => CONNECTOR_META[k].label);
    if (already.length) throw new ApiError(422, "Check the highlighted fields", { connectors: `${already.join(", ")} ${already.length === 1 ? "is" : "are"} already in this configuration` });
    if (!wanted.length) throw new ApiError(422, "Check the highlighted fields", { connectors: "Select at least one connector to add" });
    const errors = Object.fromEntries(Object.entries(validateConfigInput({ name: c.name, connectors }, DEFAULTS)).filter(([k]) => k !== "name" && wanted.some((w) => k.startsWith(`${w}.`))));
    if (Object.keys(errors).length) throw new ApiError(422, "Check the highlighted fields", errors);
    const summaries = summarise({ name: c.name, connectors });
    for (const k of wanted) c.connectors[k] = summaries[k];
    c.status = "processing";
    wanted.forEach((k, i) => setTimeout(() => { c.sources = [...(c.sources ?? []), { source: k, state: "success", documents_count: DOCS[k] }]; }, STEP_MS * (i + 1)));
    setTimeout(() => { c.status = "ready"; pinned(c); }, STEP_MS * (wanted.length + 1));
    return { ...c };
  },
  async getConfiguration(token, id) {
    auth(token);
    const c = configs.find((x) => x.id === id);
    if (!c) throw new ApiError(404, "Configuration not found");
    return { ...c, sources: c.sources ? [...c.sources] : [] };
  },
  async getGraph(token, id) {
    auth(token);
    const c = configs.find((x) => x.id === id);
    if (!c) throw new ApiError(404, "Configuration not found");
    if (c.status !== "ready") throw new ApiError(409, "The knowledge graph is not ready yet");
    return demoGraph(c);
  },
  // The real ontology of the reference packs (generated by scripts/export_ontology_json.py), not invented data.
  async getOntology(token, id) {
    auth(token);
    if (!configs.some((x) => x.id === id)) throw new ApiError(404, "Configuration not found");
    return structuredClone(ontologyFixture) as unknown as OntologyDto;
  },
  async getOntologyGraphify(token, id) {
    auth(token);
    if (!configs.some((x) => x.id === id)) throw new ApiError(404, "Configuration not found");
    return structuredClone(graphifyFixture) as unknown as GraphifyGraph;
  },
};
