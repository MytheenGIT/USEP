// The API contract between the console UI and the backend (services/connectors/console_api). Keep in sync with
// console_api/models.py and the table in ../../../README.md.
export type ConfigStatus = "submitted" | "processing" | "ready" | "failed";
export type SourceState = "pending" | "success" | "failed" | "skipped";

export type ConnectorKey = "ado" | "jira" | "confluence" | "gitlab" | "github" | "servicenow" | "figma";
export type TargetField = "project_names" | "project_keys" | "space_keys" | "project_paths" | "repositories" | "tables" | "file_keys";
/** Another way to say what to read, besides the target list: Jira's own JQL, or every GitLab or GitHub repository the token's user can reach. */
export type AlternativeField = "jql_queries" | "all_member_projects";
export type CredentialMode = "provided" | "server" | "none";
/** GitHub and GitLab: a token calls the platform API; an SSH key reads the commit history with git. */
export type AuthMethod = "token" | "ssh_key";

/**
 * What the form sends for one connector. No connector is mandatory: `enabled: false` (or leaving it out) means the
 * connector is not used and nothing else in it is checked. `api_token` is write-only: the server never returns or stores it.
 */
export interface ConnectorInput {
  enabled: boolean;
  use_server_credentials: boolean;
  base_url?: string;
  email?: string; // Atlassian: the account email. ServiceNow: the username
  api_token?: string; // the token (the password for ServiceNow); write-only
  auth_method?: AuthMethod; // GitHub and GitLab; token when left out
  ssh_key?: string; // GitHub and GitLab with auth_method "ssh_key"; write-only
  project_names?: string[]; // ado: projects to ingest
  project_keys?: string[]; // jira: any number; each is read in full
  jql_queries?: string[]; // jira: the admin's own JQL, one scope each
  space_keys?: string[]; // confluence
  project_paths?: string[]; // gitlab: any number of repositories
  repositories?: string[]; // github: owner/repo, a link, or an SSH link
  all_member_projects?: boolean; // gitlab and github: also every repository the token's user can reach
  tables?: string[]; // servicenow: incident, change_request, ...
  encoded_query?: string; // servicenow: narrows every table
  file_keys?: string[]; // figma
}

export interface ConfigInput {
  name: string;
  connectors: Partial<Record<ConnectorKey, ConnectorInput>>;
}

/** What was configured for one connector. Secrets are never part of it. */
export interface ConnectorSummary {
  enabled: boolean;
  base_url?: string | null;
  email?: string | null;
  targets: string[];
  jql_queries: string[];
  all_member_projects: boolean;
  auth_method: AuthMethod;
  encoded_query: string;
  credentials: CredentialMode;
}

/** What the server already holds for a connector (so the form can offer "use server credentials"). */
export interface ConnectorDefault {
  base_url?: string | null;
  credentials_configured: boolean;
  /** Why the connector cannot be used right now (Figma until the DPIA is signed off), else null. */
  blocked_reason?: string | null;
  /** GitHub and GitLab: whether this server can read repositories over SSH. */
  ssh_available?: boolean;
}

export interface RepositoryChoice {
  path: string;
  name: string;
  visibility?: string | null;
  description?: string | null;
}

export interface RepositoryList {
  repositories: RepositoryChoice[];
  truncated: boolean;
}

export interface ConnectionCheck {
  ok: boolean;
  message: string;
}

/** Outcome of reading one source for a configuration. `source` is a connector key. */
export interface SourceStatus {
  source: string;
  state: SourceState;
  documents_count: number;
  detail?: string | null;
}

export interface Configuration {
  id: string;
  name: string;
  connectors: Record<string, ConnectorSummary>;
  status: ConfigStatus;
  status_detail?: string | null;
  created_at: string;
  created_by: string;
  sources?: SourceStatus[];
}

export interface GraphNodeDto {
  id: string;
  concept: string; // canonical ontology concept, e.g. "Service"
  name: string;
  labels: string[]; // domain / organisation / custom labels (never replace concept)
  properties: Record<string, unknown>;
  source_system?: string | null;
  source_id?: string | null;
  confidence?: number | null; // present only for inferred nodes
  ontology_version?: string | null;
}

export interface GraphEdgeDto {
  id: string;
  source: string;
  target: string;
  relation: string; // canonical ontology relationship, e.g. "owns"
  confidence: number;
  evidence_ref?: string | null;
  source_system?: string | null;
}

export interface GraphDto {
  configuration_id: string;
  generated_at: string;
  ontology_version: string;
  nodes: GraphNodeDto[];
  edges: GraphEdgeDto[];
}

export interface Session {
  token: string;
  username: string;
}

export interface Api {
  connectorDefaults(token: string): Promise<Record<string, ConnectorDefault>>;
  testConnector(token: string, key: ConnectorKey, input: ConnectorInput): Promise<ConnectionCheck>;
  /** GitHub and GitLab: the repositories the entered token can reach, for choosing from. */
  listRepositories(token: string, key: ConnectorKey, input: ConnectorInput): Promise<RepositoryList>;
  login(username: string, password: string): Promise<Session>;
  logout(token: string): Promise<void>;
  listConfigurations(token: string): Promise<Configuration[]>;
  createConfiguration(token: string, input: ConfigInput): Promise<Configuration>;
  /** Add connectors to a configuration that is ready. Only the new ones are read; the graph is rebuilt from saved results. */
  addConnectors(token: string, id: string, connectors: ConfigInput["connectors"]): Promise<Configuration>;
  getConfiguration(token: string, id: string): Promise<Configuration>;
  getGraph(token: string, id: string): Promise<GraphDto>;
}

/** Field errors keyed "name", "connectors", or "<connector>.<field>" such as "jira.project_keys". */
export type FieldMessages = Record<string, string>;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public fields?: FieldMessages,
    public code?: string,
    public traceId?: string,
  ) {
    super(message);
  }
}
