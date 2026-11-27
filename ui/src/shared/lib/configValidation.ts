import { CONNECTOR_KEYS, CONNECTOR_META } from "../api/connectors";
import { ConfigInput, ConnectorDefault, ConnectorInput, FieldMessages } from "../api/types";

/** Quick feedback only. The API repeats every check (and adds host and format checks); the UI is never the control. */
export function validateHttpsUrl(value: string): string {
  let u: URL;
  try { u = new URL(value); } catch { return "Enter a full URL, for example https://example.com"; }
  if (u.protocol !== "https:") return "Only https:// URLs are accepted";
  if (u.username || u.password) return "Remove credentials from the URL; enter them in the credential fields";
  return "";
}

export const NO_CONNECTOR = "Select at least one connector";
const MAX_JQL = 2000;
// Mirrors console_api/validation.py's GITHUB_WEBSITE_HOST_MESSAGE.
const GITHUB_WEBSITE_HOST_MESSAGE = "That is the github.com website, not its API: use https://api.github.com (or https://<your-host>/api/v3 for GitHub Enterprise).";

/** True when the connector is selected. Anything typed into one that is not selected is ignored, as on the server. */
export const isSelected = (c: ConnectorInput | undefined): c is ConnectorInput => c?.enabled === true;

export function validateConfigInput(input: ConfigInput, defaults: Record<string, ConnectorDefault> = {}): FieldMessages {
  const errors: FieldMessages = {};
  const name = input.name.trim();
  if (!name) errors.name = "Name is required";
  else if (name.length > 80) errors.name = "Name must be 80 characters or fewer";

  // No connector is mandatory (an admin may have no Jira or no Figma), but at least one must be used, and a used one must be complete.
  const selected = CONNECTOR_KEYS.filter((k) => isSelected(input.connectors[k]));
  if (selected.length === 0) errors.connectors = NO_CONNECTOR;

  for (const key of selected) {
    const c = input.connectors[key] as ConnectorInput;
    const meta = CONNECTOR_META[key];
    const def = defaults[key];

    if (def?.blocked_reason) errors[`${key}.${meta.targetField}`] = def.blocked_reason;

    if (meta.needsBaseUrl) {
      const url = (c.base_url ?? "").trim();
      if (!url) { if (!def?.base_url) errors[`${key}.base_url`] = `${meta.label} URL is required`; }
      else {
        const bad = validateHttpsUrl(url);
        if (bad) errors[`${key}.base_url`] = bad;
        else if (key === "github" && /^https:\/\/(www\.)?github\.com\/?$/i.test(url)) errors[`${key}.base_url`] = GITHUB_WEBSITE_HOST_MESSAGE;
      }
    }
    const ssh = meta.supportsSsh && c.auth_method === "ssh_key";
    if (ssh) {
      // An SSH key reads the commit history with git. It cannot list your repositories, and the server's own credentials are tokens.
      const pem = (c.ssh_key ?? "").trim();
      if (!pem) errors[`${key}.ssh_key`] = "Paste the private key";
      else if (!pem.startsWith("-----BEGIN") || !pem.includes("PRIVATE KEY")) errors[`${key}.ssh_key`] = "Paste the whole private key, from the -----BEGIN line to the -----END line";
      if (c.use_server_credentials) errors[`${key}.api_token`] = "The server's credentials are tokens: choose the token option to use them";
      if (c.all_member_projects) errors[`${key}.all_member_projects`] = "Choosing every repository needs a token: an SSH key cannot list your repositories";
      if (!def?.ssh_available) errors[`${key}.ssh_key`] = errors[`${key}.ssh_key`] ?? "SSH access is not set up on this server";
    } else if (c.use_server_credentials) {
      if (!def?.credentials_configured) errors[`${key}.api_token`] = `The server has no ${meta.label} credentials configured`;
    } else {
      if (meta.needsEmail) {
        const identity = (c.email ?? "").trim();
        if (meta.identityKind === "username") {
          if (!identity) errors[`${key}.email`] = "Username is required";
          else if (/\s/.test(identity)) errors[`${key}.email`] = "Enter a valid username";
        } else if (!identity) errors[`${key}.email`] = "Account email is required";
        else if (!identity.includes("@")) errors[`${key}.email`] = "Enter a valid email address";
      }
      if (!(c.api_token ?? "").trim()) errors[`${key}.api_token`] = `${meta.secretLabel} is required`;
    }

    if (key === "jira") {
      const long = (c.jql_queries ?? []).some((q) => q.trim().length > MAX_JQL);
      if (long) errors["jira.jql_queries"] = `A JQL query must be at most ${MAX_JQL} characters`;
    }
    if (key === "servicenow" && (c.encoded_query ?? "").length > 1000) errors["servicenow.encoded_query"] = "The query must be at most 1000 characters";
    const targets = ((c as unknown as Record<string, unknown>)[meta.targetField] ?? []) as unknown[];
    const targetCount = Array.isArray(targets) ? targets.length : 0;
    const alternative = meta.alternative === "jql_queries" ? (c.jql_queries ?? []).some((q) => q.trim()) : meta.alternative === "all_member_projects" ? c.all_member_projects === true : false;
    if (targetCount === 0 && !alternative && !errors[`${key}.${meta.targetField}`]) errors[`${key}.${meta.targetField}`] = meta.needTargets;
  }
  return errors;
}
