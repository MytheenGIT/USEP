// DEV-ONLY in-memory API with SYNTHETIC data, used until the real API exists. It is not a security control:
// the credentials below are a development convenience and must never be reused anywhere real.
import { validateConfig } from "../validation";
import { Api, ApiError, Configuration, GraphDto } from "./types";

export const MOCK_USER = "admin";
export const MOCK_PASSWORD = "admin";
export const PROCESSING_MS = 1500;

const configs: Configuration[] = [];
const sessions = new Set<string>();

function auth(token: string) {
  if (!sessions.has(token)) throw new ApiError(401, "Not signed in");
}

function sampleGraph(c: Configuration): GraphDto {
  const repo = c.git_url.split("/").filter(Boolean).pop()?.replace(/\.git$/, "") ?? "repo";
  const n = (id: string, concept: string, name: string, extra: Partial<GraphDto["nodes"][0]> = {}) =>
    ({ id, concept, name, labels: [], properties: {}, source_system: "git", ontology_version: "0.1.0", ...extra });
  const e = (s: string, r: string, t: string, confidence = 1, source_system = "git") =>
    ({ id: `${s}-${r}-${t}`, source: s, target: t, relation: r, confidence, source_system, evidence_ref: `mock:${s}:${t}` });
  return {
    configuration_id: c.id, generated_at: new Date().toISOString(), ontology_version: "0.1.0",
    nodes: [
      n("team", "Team", "payments-team", { labels: ["Squad"], properties: { name: "payments-team" } }),
      n("svc", "Service", repo, { labels: ["architecture"], properties: { criticality: "tier_1", lifecycle_state: "active", repository_ref: repo }, source_id: repo }),
      n("api", "API", `${repo}-api`, { properties: { protocol: "rest", version: "v1" } }),
      n("data", "DataAsset", `${repo}-db`, { properties: { regulatory_scope: ["pci_dss"] } }),
      n("cap", "Capability", "Payments", { source_system: "confluence" }),
      n("req", "Requirement", "PAY-12 retry payments", { source_system: "jira" }),
      n("chg", "Change", "PAY-34 add retry", { source_system: "jira", properties: { change_state: "released" } }),
      n("env", "Environment", "production", { properties: { environment_kind: "production" } }),
      n("pol", "Policy", "Change control", { source_system: "confluence" }),
      n("inc", "Incident", "INC-101 timeout", { source_system: "jira", confidence: 0.6, properties: { severity: "sev2" } }),
      n("test", "Test", "checkout contract tests", { properties: { test_kind: "contract" } }),
    ],
    edges: [
      e("team", "owns", "svc"), e("svc", "exposes", "api"), e("svc", "consumes", "data"), e("svc", "realizes", "cap", 0.8, "confluence"),
      e("chg", "implements", "req", 1, "jira"), e("test", "tests", "svc"), e("svc", "deployed_to", "env"),
      e("svc", "governed_by", "pol", 1, "confluence"), e("inc", "caused_by", "chg", 0.6, "jira"),
    ],
  };
}

export const mockApi: Api = {
  async login(username, password) {
    if (username !== MOCK_USER || password !== MOCK_PASSWORD) throw new ApiError(401, "Invalid username or password");
    const token = crypto.randomUUID();
    sessions.add(token);
    return { token, username };
  },
  async logout(token) { sessions.delete(token); },
  async listConfigurations(token) { auth(token); return configs.map((c) => ({ ...c })); },
  async createConfiguration(token, input) {
    auth(token);
    const errors = validateConfig(input);
    if (Object.keys(errors).length) throw new ApiError(422, "Validation failed", errors);
    const c: Configuration = { ...input, id: crypto.randomUUID(), status: "processing", created_at: new Date().toISOString(), created_by: MOCK_USER };
    configs.unshift(c);
    setTimeout(() => { c.status = "ready"; }, PROCESSING_MS);
    return { ...c };
  },
  async getConfiguration(token, id) {
    auth(token);
    const c = configs.find((x) => x.id === id);
    if (!c) throw new ApiError(404, "Configuration not found");
    return { ...c };
  },
  async getGraph(token, id) {
    auth(token);
    const c = configs.find((x) => x.id === id);
    if (!c) throw new ApiError(404, "Configuration not found");
    if (c.status !== "ready") throw new ApiError(409, "The knowledge graph is not ready yet");
    return sampleGraph(c);
  },
};
