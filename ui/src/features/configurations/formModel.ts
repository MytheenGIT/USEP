import { CONNECTOR_KEYS, CONNECTOR_META } from "../../shared/api/connectors";
import { AuthMethod, ConfigInput, Configuration, ConnectorDefault, ConnectorInput, ConnectorKey, FieldMessages } from "../../shared/api/types";
import { validateConfigInput } from "../../shared/lib/configValidation";

/** The form's own state. Kept apart from the wire shape so typing never has to produce a valid payload. */
export interface ConnectorForm {
  /** Used at all? No connector is mandatory; one that is off is not checked and not sent. */
  enabled: boolean;
  useServerCredentials: boolean;
  text: { base_url: string; email: string; api_token: string };
  tags: string[];
  /** Jira: the admin's own JQL, one query per line. */
  jql: string;
  /** GitLab and GitHub: also read every repository the token's user can reach. */
  allMemberProjects: boolean;
  /** GitLab and GitHub: sign in with a token, or read the commit history over SSH with a key. */
  authMethod: AuthMethod;
  sshKey: string;
  /** ServiceNow: an encoded query that narrows every table. */
  encodedQuery: string;
}

export interface FormState {
  name: string;
  connectors: Record<ConnectorKey, ConnectorForm>;
}

export const emptyConnector = (): ConnectorForm => ({
  enabled: false, useServerCredentials: false, text: { base_url: "", email: "", api_token: "" }, tags: [], jql: "", allMemberProjects: false,
  authMethod: "token", sshKey: "", encodedQuery: "",
});

export const emptyForm = (): FormState => ({
  name: "",
  connectors: Object.fromEntries(CONNECTOR_KEYS.map((k) => [k, emptyConnector()])) as Record<ConnectorKey, ConnectorForm>,
});

/** A copy of an existing configuration as a starting point. Tokens are never kept by the server, so they start empty. */
export function formFromConfiguration(c: Configuration): FormState {
  const form = emptyForm();
  form.name = c.name;
  for (const key of CONNECTOR_KEYS) {
    const s = c.connectors[key];
    if (!s?.enabled) continue;
    form.connectors[key] = {
      enabled: true,
      useServerCredentials: s.credentials === "server",
      text: { base_url: s.base_url ?? "", email: s.email ?? "", api_token: "" },
      tags: [...s.targets],
      jql: (s.jql_queries ?? []).join("\n"),
      allMemberProjects: s.all_member_projects ?? false,
      authMethod: s.auth_method ?? "token",
      sshKey: "",
      encodedQuery: s.encoded_query ?? "",
    };
  }
  return form;
}

/** One JQL per line; blank lines and repeats are dropped. */
export const jqlLines = (text: string): string[] => [...new Set(text.split("\n").map((l) => l.trim()).filter(Boolean))];

export function connectorPayload(key: ConnectorKey, f: ConnectorForm): ConnectorInput {
  const meta = CONNECTOR_META[key];
  const input: ConnectorInput = { enabled: true, use_server_credentials: f.useServerCredentials };
  if (meta.needsBaseUrl) input.base_url = f.text.base_url.trim();
  const ssh = meta.supportsSsh && f.authMethod === "ssh_key";
  if (meta.supportsSsh) input.auth_method = f.authMethod;
  if (ssh) input.ssh_key = f.sshKey.trim();
  else {
    if (meta.needsEmail && !f.useServerCredentials) input.email = f.text.email.trim();
    if (!f.useServerCredentials) input.api_token = f.text.api_token.trim();
  }
  (input as unknown as Record<string, unknown>)[meta.targetField] = f.tags;
  if (key === "jira") input.jql_queries = jqlLines(f.jql);
  if (meta.alternative === "all_member_projects") input.all_member_projects = f.allMemberProjects && !ssh;
  if (key === "servicenow") input.encoded_query = f.encodedQuery.trim();
  return input;
}

/** Only the connectors that are switched on are sent in full; the others go as `enabled: false`. */
export function toPayload(form: FormState): ConfigInput {
  return {
    name: form.name.trim(),
    connectors: Object.fromEntries(
      CONNECTOR_KEYS.map((k) => [k, form.connectors[k].enabled ? connectorPayload(k, form.connectors[k]) : { enabled: false, use_server_credentials: false }]),
    ) as Record<ConnectorKey, ConnectorInput>,
  };
}

export const validateForm = (form: FormState, defaults: Record<string, ConnectorDefault>): FieldMessages =>
  validateConfigInput(toPayload(form), defaults);

/** Per-card state: not used, needs input, or complete. Whether it will actually connect is what Test connection tells. */
export function connectorState(key: ConnectorKey, f: ConnectorForm, defaults: Record<string, ConnectorDefault>): "off" | "incomplete" | "complete" {
  if (!f.enabled) return "off";
  const errors = validateConfigInput({ name: "x", connectors: { [key]: connectorPayload(key, f) } }, defaults);
  return Object.keys(errors).some((k) => k.startsWith(`${key}.`)) ? "incomplete" : "complete";
}

export const selectedCount = (form: FormState): number => CONNECTOR_KEYS.filter((k) => form.connectors[k].enabled).length;

export const completeCount = (form: FormState, defaults: Record<string, ConnectorDefault>): number =>
  CONNECTOR_KEYS.filter((k) => connectorState(k, form.connectors[k], defaults) === "complete").length;

/** The connectors a configuration does not use yet, so they can be added to it. */
export const addableConnectors = (c: Pick<Configuration, "connectors">): ConnectorKey[] => CONNECTOR_KEYS.filter((k) => !c.connectors[k]?.enabled);
