import { AlternativeField, ConnectorKey, TargetField } from "../../../shared/api/types";

/** UI-only description of one input on a connector card. The contract-level facts live in shared/api/connectors.ts. */
export interface FieldDef {
  key: "base_url" | "email" | "api_token" | "ssh_key" | "encoded_query" | TargetField | AlternativeField;
  kind: "url" | "text" | "secret" | "tags" | "lines" | "toggle" | "sshkey";
  label: string;
  placeholder: string;
  hint?: string;
  /** Part of how the connector signs in with a token: hidden when the admin uses the server's credentials or an SSH key. */
  credential?: boolean;
  /** Tags: common values offered as one-click pills. */
  suggestions?: string[];
}

export interface ConnectorDef {
  key: ConnectorKey;
  blurb: string;
  fields: FieldDef[];
}

/** To add a connector: add its meta in shared/api/connectors.ts, then describe its card here. */
export const CONNECTOR_DEFS: ConnectorDef[] = [
  {
    key: "ado",
    blurb: "Work items, pull requests and repositories from Azure DevOps projects.",
    fields: [
      { key: "base_url", kind: "url", label: "Azure DevOps URL", placeholder: "https://dev.azure.com/your-organization" },
      { key: "api_token", kind: "secret", label: "Token", placeholder: "Paste the token", credential: true, hint: "A Personal Access Token (PAT) with read access. It is not stored." },
      { key: "project_names", kind: "tags", label: "Projects", placeholder: "MyProject, then Enter", hint: "Add the Azure DevOps projects you want to ingest. Each one is read in full." },
    ],
  },
  {
    key: "jira",
    blurb: "Issues, comments and history from Jira Cloud projects.",
    fields: [
      { key: "base_url", kind: "url", label: "Jira site URL", placeholder: "https://your-company.atlassian.net" },
      { key: "email", kind: "text", label: "Account email", placeholder: "you@your-company.com", credential: true },
      { key: "api_token", kind: "secret", label: "Token", placeholder: "Paste the token", credential: true, hint: "Create one at id.atlassian.com under Security, API tokens. It is sent to the server and not stored." },
      { key: "project_keys", kind: "tags", label: "Project keys", placeholder: "PAY, then Enter (or paste a project link)", hint: "Add as many projects as you need. Each one is read in full." },
      { key: "jql_queries", kind: "lines", label: "JQL queries (optional)", placeholder: "project = PAY AND labels = release", hint: "Your own JQL, one query per line. Use it instead of project keys, or as well. Leave out the date filter: the service adds it." },
    ],
  },
  {
    key: "confluence",
    blurb: "Pages, labels and version history from Confluence Cloud spaces.",
    fields: [
      { key: "base_url", kind: "url", label: "Confluence site URL", placeholder: "https://your-company.atlassian.net" },
      { key: "email", kind: "text", label: "Account email", placeholder: "you@your-company.com", credential: true },
      { key: "api_token", kind: "secret", label: "Token", placeholder: "Paste the token", credential: true, hint: "The same Atlassian token type as Jira. It is not stored." },
      { key: "space_keys", kind: "tags", label: "Space keys", placeholder: "ENG, then Enter (or paste a space link)", hint: "Add as many spaces as you need. Each one is read on its own." },
    ],
  },
  {
    key: "gitlab",
    blurb: "Merge requests, commits, comments, approvals and diffs from GitLab projects.",
    fields: [
      { key: "base_url", kind: "url", label: "GitLab URL", placeholder: "https://gitlab.com or your self-hosted address" },
      { key: "api_token", kind: "secret", label: "Token", placeholder: "Paste the token", credential: true, hint: "A personal or project access token with the read_api scope. It is not stored." },
      { key: "ssh_key", kind: "sshkey", label: "Private SSH key", placeholder: "-----BEGIN OPENSSH PRIVATE KEY-----", hint: "A key without a passphrase, for read access only. It is used for this run and not stored. It reads commit history; merge requests and comments need a token." },
      { key: "project_paths", kind: "tags", label: "Repositories", placeholder: "group/project, a link, or an SSH link, then Enter", hint: "Add every repository you work in. Links and SSH links (git@gitlab.com:group/project.git) are accepted." },
      { key: "all_member_projects", kind: "toggle", label: "Read every repository I am a member of", placeholder: "", hint: "Finds them with your token and keeps looking for new ones. Archived repositories are skipped. This can include repositories nobody has approved." },
    ],
  },
  {
    key: "github",
    blurb: "Pull requests, commits, comments, reviews and changed files from GitHub repositories.",
    fields: [
      { key: "base_url", kind: "url", label: "GitHub API URL", placeholder: "https://api.github.com (or https://your-host/api/v3)" },
      { key: "api_token", kind: "secret", label: "Token", placeholder: "Paste the token", credential: true, hint: "A personal access token that can read the repositories. It is not stored." },
      { key: "ssh_key", kind: "sshkey", label: "Private SSH key", placeholder: "-----BEGIN OPENSSH PRIVATE KEY-----", hint: "A key without a passphrase, for read access only. It is used for this run and not stored. It reads commit history; pull requests and reviews need a token." },
      { key: "repositories", kind: "tags", label: "Repositories", placeholder: "owner/repo, a link, or an SSH link, then Enter", hint: "Add every repository you work in. Links and SSH links (git@github.com:owner/repo.git) are accepted." },
      { key: "all_member_projects", kind: "toggle", label: "Read every repository I can reach", placeholder: "", hint: "Finds them with your token and keeps looking for new ones. Archived repositories are skipped. This can include repositories nobody has approved." },
    ],
  },
  {
    key: "servicenow",
    blurb: "Incidents, change requests and problems from a ServiceNow instance.",
    fields: [
      { key: "base_url", kind: "url", label: "Instance URL", placeholder: "https://your-instance.service-now.com" },
      { key: "email", kind: "text", label: "Username", placeholder: "A read-only integration user", credential: true },
      { key: "api_token", kind: "secret", label: "Password", placeholder: "Paste the password", credential: true, hint: "The integration user's password. It is sent to the server and not stored." },
      { key: "tables", kind: "tags", label: "Tables", placeholder: "incident, then Enter", hint: "Each table is read on its own.", suggestions: ["incident", "change_request", "problem"] },
      { key: "encoded_query", kind: "text", label: "Filter (optional)", placeholder: "active=true^priority<=2", hint: "A ServiceNow encoded query that narrows every table." },
    ],
  },
  {
    key: "figma",
    blurb: "Pages, frames and text from Figma files. Images are never downloaded.",
    fields: [
      { key: "api_token", kind: "secret", label: "Token", placeholder: "Paste the token", credential: true, hint: "A personal access token that can read the files. It is not stored." },
      { key: "file_keys", kind: "tags", label: "Files", placeholder: "Paste a file link or key, then Enter", hint: "The key is the part after /design/ in the file link." },
    ],
  },
];
