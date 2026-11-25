// The API contract the UI expects. The API is built later; it must serve exactly these shapes (see ../../README.md).
export type ConfigStatus = "submitted" | "processing" | "ready" | "failed";

export interface ConfigInput {
  name: string;
  git_url: string;
  jira_url: string;
  confluence_url: string;
  figma_url: string;
  ad_url: string;
}

export interface Configuration extends ConfigInput {
  id: string;
  status: ConfigStatus;
  status_detail?: string;
  created_at: string;
  created_by: string;
}

export interface GraphNodeDto {
  id: string;
  concept: string;           // canonical ontology concept, e.g. "Service"
  name: string;
  labels: string[];          // domain / organisation / custom labels (never replace concept)
  properties: Record<string, unknown>;
  source_system?: string;
  source_id?: string;
  confidence?: number;       // present only for inferred nodes
  ontology_version?: string;
}

export interface GraphEdgeDto {
  id: string;
  source: string;
  target: string;
  relation: string;          // canonical ontology relationship, e.g. "owns"
  confidence: number;
  evidence_ref?: string;
  source_system?: string;
}

export interface GraphDto {
  configuration_id: string;
  generated_at: string;
  ontology_version: string;
  nodes: GraphNodeDto[];
  edges: GraphEdgeDto[];
}

export interface Session { token: string; username: string; }

export interface Api {
  login(username: string, password: string): Promise<Session>;
  logout(token: string): Promise<void>;
  listConfigurations(token: string): Promise<Configuration[]>;
  createConfiguration(token: string, input: ConfigInput): Promise<Configuration>;
  getConfiguration(token: string, id: string): Promise<Configuration>;
  getGraph(token: string, id: string): Promise<GraphDto>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public fields?: Partial<Record<keyof ConfigInput, string>>) {
    super(message);
  }
}
