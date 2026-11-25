import { mockApi } from "./mock";
import { Api, ApiError, ConfigInput } from "./types";

async function call<T>(method: string, path: string, token?: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail: { message?: string; fields?: Partial<Record<keyof ConfigInput, string>> } = {};
    try { detail = await res.json(); } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, detail.message ?? `Request failed (${res.status})`, detail.fields);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const httpApi: Api = {
  login: (username, password) => call("POST", "/auth/login", undefined, { username, password }),
  logout: (token) => call("POST", "/auth/logout", token),
  listConfigurations: (t) => call("GET", "/configurations", t),
  createConfiguration: (t, input) => call("POST", "/configurations", t, input),
  getConfiguration: (t, id) => call("GET", `/configurations/${encodeURIComponent(id)}`, t),
  getGraph: (t, id) => call("GET", `/configurations/${encodeURIComponent(id)}/graph`, t),
};

export const api: Api = import.meta.env.VITE_USE_MOCK === "false" ? httpApi : mockApi;
export const usingMock = import.meta.env.VITE_USE_MOCK !== "false";
