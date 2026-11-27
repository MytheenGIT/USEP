import { describe, expect, it } from "vitest";
import { Configuration } from "../../shared/api/types";
import { addableConnectors, completeCount, connectorState, emptyForm, formFromConfiguration, jqlLines, selectedCount, toPayload, validateForm } from "./formModel";

const on = { enabled: true, useServerCredentials: false, jql: "", allMemberProjects: false, authMethod: "token" as const, sshKey: "", encodedQuery: "" };
const complete = () => {
  const f = emptyForm();
  f.name = "  Payments ";
  const atlassian = { ...on, text: { base_url: " https://acme.atlassian.net ", email: "a@b.co", api_token: " tok " }, tags: ["PAY"] };
  f.connectors.jira = { ...atlassian };
  f.connectors.confluence = { ...atlassian, tags: ["ENG", "OPS"] };
  f.connectors.gitlab = { ...on, text: { base_url: "https://gitlab.example.com", email: "", api_token: "gl" }, tags: ["a/b", "a/c"] };
  f.connectors.figma = { ...on, text: { base_url: "", email: "", api_token: "fg" }, tags: ["AbCdEf1234567890"] };
  return f;
};

describe("formModel", () => {
  it("builds a trimmed payload with only the fields each connector needs", () => {
    const p = toPayload(complete());
    expect(p.name).toBe("Payments");
    expect(p.connectors.jira).toEqual({ enabled: true, use_server_credentials: false, base_url: "https://acme.atlassian.net", email: "a@b.co", api_token: "tok", project_keys: ["PAY"], jql_queries: [] });
    expect(p.connectors.gitlab).toEqual({ enabled: true, use_server_credentials: false, base_url: "https://gitlab.example.com", api_token: "gl", project_paths: ["a/b", "a/c"], auth_method: "token", all_member_projects: false });
    expect(p.connectors.figma).toEqual({ enabled: true, use_server_credentials: false, api_token: "fg", file_keys: ["AbCdEf1234567890"] });
    expect(p.connectors.figma && "base_url" in p.connectors.figma).toBe(false);
  });

  it("sends a connector that is switched off as not used, and nothing typed into it", () => {
    const f = complete();
    f.connectors.figma = { ...f.connectors.figma, enabled: false };
    f.connectors.jira = { ...f.connectors.jira, enabled: false };
    const p = toPayload(f);
    expect(p.connectors.figma).toEqual({ enabled: false, use_server_credentials: false });
    expect(p.connectors.jira).toEqual({ enabled: false, use_server_credentials: false });
    expect(p.connectors.gitlab?.enabled).toBe(true);
  });

  it("starts with every connector switched off, so none is mandatory", () => {
    const f = emptyForm();
    expect(selectedCount(f)).toBe(0);
    expect(Object.values(toPayload(f).connectors).every((c) => c?.enabled === false)).toBe(true);
  });

  it("splits Jira's JQL into one query per line and drops blanks and repeats", () => {
    expect(jqlLines("labels = a\n\n  labels = a  \nassignee = currentUser()\n")).toEqual(["labels = a", "assignee = currentUser()"]);
    const f = complete();
    f.connectors.jira = { ...f.connectors.jira, tags: [], jql: "labels = a\nlabels = b" };
    expect(toPayload(f).connectors.jira?.jql_queries).toEqual(["labels = a", "labels = b"]);
  });

  it("omits typed credentials when the server's are used", () => {
    const f = complete();
    f.connectors.jira.useServerCredentials = true;
    const jira = toPayload(f).connectors.jira!;
    expect("api_token" in jira || "email" in jira).toBe(false);
  });

  it("is valid with one connector and refuses none", () => {
    expect(validateForm(complete(), {})).toEqual({});
    const one = emptyForm();
    one.name = "Only Jira";
    one.connectors.jira = { ...complete().connectors.jira };
    expect(validateForm(one, {})).toEqual({});
    one.connectors.jira.enabled = false;
    expect(validateForm(one, {})).toEqual({ connectors: "Select at least one connector" });
  });

  it("checks only the connectors that are switched on", () => {
    const f = emptyForm();
    f.name = "x";
    f.connectors.confluence = { ...on, text: { base_url: "", email: "", api_token: "" }, tags: [] };
    const keys = Object.keys(validateForm(f, {}));
    expect(keys.every((k) => k.startsWith("confluence."))).toBe(true);
    expect(keys.sort()).toEqual(["confluence.api_token", "confluence.base_url", "confluence.email", "confluence.space_keys"]);
  });

  it("accepts Jira with only a JQL, and GitLab with only 'all my repositories'", () => {
    const f = complete();
    f.connectors.jira = { ...f.connectors.jira, tags: [], jql: "labels = release" };
    f.connectors.gitlab = { ...f.connectors.gitlab, tags: [], allMemberProjects: true };
    expect(validateForm(f, {})).toEqual({});
    f.connectors.jira = { ...f.connectors.jira, jql: "  \n " };
    f.connectors.gitlab = { ...f.connectors.gitlab, allMemberProjects: false };
    expect(validateForm(f, {})).toEqual({
      "jira.project_keys": "Add at least one project key or a JQL query",
      "gitlab.project_paths": "Add at least one repository, or choose all repositories you are a member of",
    });
  });

  it("builds GitHub, ServiceNow and SSH payloads with only what each needs", () => {
    const f = emptyForm();
    f.name = "x";
    f.connectors.github = { ...on, text: { base_url: "", email: "", api_token: "gh" }, tags: ["acme/a", "acme/b"], allMemberProjects: true };
    f.connectors.servicenow = { ...on, text: { base_url: "https://dev1.service-now.com", email: "svc", api_token: "pw" }, tags: ["incident"], encodedQuery: " active=true " };
    f.connectors.gitlab = { ...on, text: { base_url: "https://gitlab.com", email: "ignored", api_token: "ignored" }, tags: ["g/p"], authMethod: "ssh_key", sshKey: "  KEY  ", allMemberProjects: true };
    const p = toPayload(f).connectors;
    expect(p.github).toEqual({ enabled: true, use_server_credentials: false, base_url: "", api_token: "gh", auth_method: "token", repositories: ["acme/a", "acme/b"], all_member_projects: true });
    expect(p.servicenow).toEqual({ enabled: true, use_server_credentials: false, base_url: "https://dev1.service-now.com", email: "svc", api_token: "pw", tables: ["incident"], encoded_query: "active=true" });
    // an SSH key replaces the token, and "every repository" cannot be used with it (a key cannot list repositories)
    expect(p.gitlab).toEqual({ enabled: true, use_server_credentials: false, base_url: "https://gitlab.com", auth_method: "ssh_key", ssh_key: "KEY", project_paths: ["g/p"], all_member_projects: false });
  });

  it("will not use a connector the server has blocked", () => {
    const f = emptyForm();
    f.name = "x";
    f.connectors.figma = { ...complete().connectors.figma };
    expect(validateForm(f, { figma: { credentials_configured: false, blocked_reason: "Figma waits for the DPIA" } })["figma.file_keys"]).toBe("Figma waits for the DPIA");
  });

  it("labels each card off, incomplete or complete and counts them", () => {
    const f = complete();
    expect(connectorState("jira", f.connectors.jira, {})).toBe("complete");
    f.connectors.gitlab = { ...emptyForm().connectors.gitlab, enabled: true };
    expect(connectorState("gitlab", f.connectors.gitlab, {})).toBe("incomplete");
    f.connectors.figma = { ...f.connectors.figma, enabled: false };
    expect(connectorState("figma", f.connectors.figma, {})).toBe("off");
    expect(selectedCount(f)).toBe(3);
    expect(completeCount(f, {})).toBe(2);
  });

  it("copies a configuration as a template without any token, keeping which connectors were used", () => {
    const c: Configuration = {
      id: "i", name: "Payments", status: "ready", created_at: "", created_by: "admin",
      connectors: {
        jira: { enabled: true, base_url: "https://acme.atlassian.net", email: "a@b.co", targets: ["PAY", "OPS"], jql_queries: ["labels = a"], all_member_projects: false, auth_method: "token", encoded_query: "", credentials: "provided" },
        gitlab: { enabled: true, base_url: "https://gitlab.com", targets: [], jql_queries: [], all_member_projects: true, auth_method: "token", encoded_query: "", credentials: "provided" },
        figma: { enabled: false, targets: [], jql_queries: [], all_member_projects: false, auth_method: "token", encoded_query: "", credentials: "none" },
      },
    };
    const f = formFromConfiguration(c);
    expect(f.connectors.jira).toEqual({ enabled: true, useServerCredentials: false, text: { base_url: "https://acme.atlassian.net", email: "a@b.co", api_token: "" }, tags: ["PAY", "OPS"], jql: "labels = a", allMemberProjects: false, authMethod: "token", sshKey: "", encodedQuery: "" });
    expect(f.connectors.gitlab.allMemberProjects).toBe(true);
    expect(f.connectors.figma.enabled).toBe(false);
    expect(f.connectors.confluence).toEqual(emptyForm().connectors.confluence);
  });

  it("offers only the connectors a configuration does not use yet", () => {
    const summary = (enabled: boolean) => ({ enabled, targets: [], jql_queries: [], all_member_projects: false, auth_method: "token" as const, encoded_query: "", credentials: "none" as const });
    expect(addableConnectors({ connectors: { jira: summary(true), gitlab: summary(true), figma: summary(false) } })).toEqual(["confluence", "github", "servicenow", "figma"]);
    expect(addableConnectors({ connectors: {} })).toHaveLength(6);
  });
});
