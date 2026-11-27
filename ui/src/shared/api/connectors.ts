import { AlternativeField, ConnectorKey, TargetField } from "./types";

/** Contract-level facts about each connector. Mirrors SPECS in services/connectors/console_api/validation.py. */
export interface ConnectorMeta {
  key: ConnectorKey;
  label: string;
  needsBaseUrl: boolean;
  /** An identity next to the secret: the Atlassian account email, or the ServiceNow username. */
  needsEmail: boolean;
  identityKind?: "email" | "username";
  targetField: TargetField;
  targetLabel: string;
  secretLabel: string;
  /** A second way to say what to read; the target list may then stay empty. */
  alternative?: AlternativeField;
  /** What to tell the admin when neither is given. */
  needTargets: string;
  /** GitHub and GitLab: an SSH key may be given instead of a token. */
  supportsSsh: boolean;
}

export const CONNECTOR_META: Record<ConnectorKey, ConnectorMeta> = {
  ado: {
    key: "ado",
    label: "Azure DevOps",
    needsBaseUrl: true,
    needsEmail: false,
    targetField: "project_names",
    targetLabel: "Projects",
    secretLabel: "Token",
    alternative: undefined,
    needTargets: "Add at least one project",
    supportsSsh: false,
  },
  jira: { key: "jira", label: "Jira", needsBaseUrl: true, needsEmail: true, identityKind: "email", targetField: "project_keys", targetLabel: "Project keys", secretLabel: "Token", alternative: "jql_queries", needTargets: "Add at least one project key or a JQL query", supportsSsh: false },
  confluence: { key: "confluence", label: "Confluence", needsBaseUrl: true, needsEmail: true, identityKind: "email", targetField: "space_keys", targetLabel: "Space keys", secretLabel: "Token", needTargets: "Add at least one: space keys", supportsSsh: false },
  gitlab: { key: "gitlab", label: "GitLab", needsBaseUrl: true, needsEmail: false, identityKind: "email", targetField: "project_paths", targetLabel: "Projects", secretLabel: "Token", alternative: "all_member_projects", needTargets: "Add at least one repository, or choose all repositories you are a member of", supportsSsh: true },
  github: { key: "github", label: "GitHub", needsBaseUrl: true, needsEmail: false, identityKind: "email", targetField: "repositories", targetLabel: "Repositories", secretLabel: "Token", alternative: "all_member_projects", needTargets: "Add at least one repository, or choose all repositories you can reach", supportsSsh: true },
  servicenow: { key: "servicenow", label: "ServiceNow", needsBaseUrl: true, needsEmail: true, identityKind: "username", targetField: "tables", targetLabel: "Tables", secretLabel: "Password", needTargets: "Add at least one table, for example incident", supportsSsh: false },
  figma: { key: "figma", label: "Figma", needsBaseUrl: false, needsEmail: false, identityKind: "email", targetField: "file_keys", targetLabel: "Files", secretLabel: "Token", needTargets: "Add at least one: files", supportsSsh: false },
};

export const CONNECTOR_KEYS = Object.keys(CONNECTOR_META) as ConnectorKey[];
