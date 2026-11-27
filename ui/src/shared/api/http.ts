import { Api, ApiError, FieldMessages } from "./types";

interface ErrorBody {
  message?: string;
  code?: string;
  trace_id?: string;
  fields?: FieldMessages;
}

/** Calls the backend. Paths are relative to /api (the dev server proxies /api to VITE_API_TARGET). */
async function call<T>(method: string, path: string, token?: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the API. Check that the backend is running.", undefined, "network");
  }
  if (!res.ok) {
    let detail: ErrorBody = {};
    try {
      detail = (await res.json()) as ErrorBody;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail.message ?? `Request failed (${res.status})`, detail.fields, detail.code, detail.trace_id);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const httpApi: Api = {
  connectorDefaults: (t) => call("GET", "/connector-defaults", t),
  testConnector: (t, key, input) => call("POST", `/connectors/${encodeURIComponent(key)}/test`, t, input),
  listRepositories: (t, key, input) => call("POST", `/connectors/${encodeURIComponent(key)}/repositories`, t, input),
  login: (username, password) => call("POST", "/auth/login", undefined, { username, password }),
  logout: (token) => call("POST", "/auth/logout", token),
  listConfigurations: (t) => call("GET", "/configurations", t),
  createConfiguration: (t, input) => call("POST", "/configurations", t, input),
  addConnectors: (t, id, connectors) => call("POST", `/configurations/${encodeURIComponent(id)}/connectors`, t, { connectors }),
  getConfiguration: (t, id) => call("GET", `/configurations/${encodeURIComponent(id)}`, t),
  getGraph: (t, id) => call("GET", `/configurations/${encodeURIComponent(id)}/graph`, t),
  getOntology: (t, id) => call("GET", `/configurations/${encodeURIComponent(id)}/ontology`, t),
  getOntologyGraphify: (t, id) => call("GET", `/configurations/${encodeURIComponent(id)}/ontology/graphify`, t),
};
