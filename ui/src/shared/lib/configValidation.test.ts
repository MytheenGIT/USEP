import { describe, expect, it } from "vitest";
import { ConfigInput, ConnectorInput } from "../api/types";
import { validateConfigInput, validateHttpsUrl } from "./configValidation";

const off: ConnectorInput = { enabled: false, use_server_credentials: false };
const gitlab: ConnectorInput = { enabled: true, use_server_credentials: false, base_url: "https://gitlab.example.com", api_token: "t", project_paths: ["a/b"] };
const figma: ConnectorInput = { enabled: true, use_server_credentials: false, api_token: "t", file_keys: ["AbCdEf1234567890"] };
const confluence: ConnectorInput = { enabled: true, use_server_credentials: false, base_url: "https://acme.atlassian.net", email: "a@b.co", api_token: "t", space_keys: ["PAY", "OPS"] };
const jira: ConnectorInput = { enabled: true, use_server_credentials: false, base_url: "https://acme.atlassian.net", email: "a@b.co", api_token: "t", project_keys: ["PAY", "OPS"] };
const blank: ConnectorInput = { enabled: true, use_server_credentials: false };
const all = (over: ConfigInput["connectors"] = {}, name = "Pay"): ConfigInput => ({ name, connectors: { jira, confluence, gitlab, figma, ...over } });
const only = (connectors: ConfigInput["connectors"], name = "Pay"): ConfigInput => ({ name, connectors });

describe("validateHttpsUrl", () => {
  it("accepts https and refuses http, junk and embedded credentials", () => {
    expect(validateHttpsUrl("https://acme.atlassian.net")).toBe("");
    expect(validateHttpsUrl("http://acme.atlassian.net")).toMatch(/https/);
    expect(validateHttpsUrl("acme")).toMatch(/full URL/);
    expect(validateHttpsUrl("https://u:p@acme.atlassian.net")).toMatch(/credentials/);
  });
});

describe("validateConfigInput", () => {
  it("accepts a configuration where every selected connector is complete", () => {
    expect(validateConfigInput(all())).toEqual({});
  });
  it("requires a name", () => {
    expect(validateConfigInput(all({}, ""))).toEqual({ name: "Name is required" });
    expect(validateConfigInput(all({}, "x".repeat(81))).name).toMatch(/80/);
  });
  it("makes no connector mandatory: any one is enough, and the others can be absent or switched off", () => {
    expect(validateConfigInput(only({ jira }))).toEqual({});
    expect(validateConfigInput(only({ gitlab, jira: off, figma: off }))).toEqual({});
    expect(validateConfigInput(only({ figma }))).toEqual({});
  });
  it("needs at least one connector to be used", () => {
    expect(validateConfigInput(only({}))).toEqual({ connectors: "Select at least one connector" });
    expect(validateConfigInput(only({ jira: off, gitlab: off }))).toEqual({ connectors: "Select at least one connector" });
  });
  it("ignores everything typed into a connector that is not used", () => {
    const junk: ConnectorInput = { enabled: false, use_server_credentials: false, base_url: "http://bad", project_keys: ["not valid"] };
    expect(validateConfigInput(all({ figma: junk }))).toEqual({});
  });
  it("reports each missing field of a selected connector, keyed connector.field, and only for that connector", () => {
    expect(Object.keys(validateConfigInput(only({ jira: blank, gitlab: off }))).sort()).toEqual(["jira.api_token", "jira.base_url", "jira.email", "jira.project_keys"]);
  });
  it("gitlab and figma need no email; figma needs no URL", () => {
    expect(validateConfigInput(only({ gitlab, figma }))).toEqual({});
  });
  it("lets Jira take several project keys, or only JQL, but not neither", () => {
    const noTargets = { ...jira, project_keys: [] };
    expect(validateConfigInput(only({ jira: noTargets }))).toEqual({ "jira.project_keys": "Add at least one project key or a JQL query" });
    expect(validateConfigInput(only({ jira: { ...noTargets, jql_queries: ["labels = release"] } }))).toEqual({});
    expect(validateConfigInput(only({ jira: { ...noTargets, jql_queries: ["  "] } }))).toEqual({ "jira.project_keys": "Add at least one project key or a JQL query" });
    expect(validateConfigInput(only({ jira: { ...jira, jql_queries: ["x".repeat(2001)] } }))["jira.jql_queries"]).toMatch(/2000/);
  });
  it("lets GitLab take several repositories, or every repository the user is a member of, but not neither", () => {
    const noTargets = { ...gitlab, project_paths: [] };
    expect(validateConfigInput(only({ gitlab: noTargets }))["gitlab.project_paths"]).toMatch(/all repositories/);
    expect(validateConfigInput(only({ gitlab: { ...noTargets, all_member_projects: true } }))).toEqual({});
  });
  it("needs at least one Confluence space and one Figma file", () => {
    expect(validateConfigInput(only({ confluence: { ...confluence, space_keys: [] } }))).toEqual({ "confluence.space_keys": "Add at least one: space keys" });
    expect(validateConfigInput(only({ figma: { ...figma, file_keys: [] } }))).toEqual({ "figma.file_keys": "Add at least one: files" });
  });
  it("lets server credentials and a server URL stand in for typed ones, but only when the server has them", () => {
    const c: ConnectorInput = { enabled: true, use_server_credentials: true, project_keys: ["PAY"] };
    expect(Object.keys(validateConfigInput(only({ jira: c })))).toEqual(["jira.base_url", "jira.api_token"]);
    expect(validateConfigInput(only({ jira: c }), { jira: { base_url: "https://acme.atlassian.net", credentials_configured: true } })).toEqual({});
  });
  it("treats GitHub like GitLab: a token and repositories, or every repository", () => {
    const github: ConnectorInput = { enabled: true, use_server_credentials: false, base_url: "https://api.github.com", api_token: "t", repositories: ["acme/a"] };
    expect(validateConfigInput(only({ github }))).toEqual({});
    expect(validateConfigInput(only({ github: { ...github, repositories: [] } }))["github.repositories"]).toMatch(/all repositories you can reach/);
    expect(validateConfigInput(only({ github: { ...github, repositories: [], all_member_projects: true } }))).toEqual({});
    expect(validateConfigInput(only({ github: { ...github, api_token: "" } }))).toEqual({ "github.api_token": "Token is required" });
  });
  it("asks ServiceNow for a username (not an email), a password and tables", () => {
    const servicenow: ConnectorInput = { enabled: true, use_server_credentials: false, base_url: "https://dev1.service-now.com", email: "svc-ingest", api_token: "pw", tables: ["incident"] };
    expect(validateConfigInput(only({ servicenow }))).toEqual({});
    expect(validateConfigInput(only({ servicenow: { enabled: true, use_server_credentials: false } }))).toEqual({
      "servicenow.base_url": "ServiceNow URL is required", "servicenow.email": "Username is required",
      "servicenow.api_token": "Password is required", "servicenow.tables": "Add at least one table, for example incident",
    });
    expect(validateConfigInput(only({ servicenow: { ...servicenow, email: "has space" } }))["servicenow.email"]).toBe("Enter a valid username");
  });
  it("calls the secret a token everywhere", () => {
    for (const [key, c] of [["jira", jira], ["confluence", confluence], ["gitlab", gitlab], ["figma", figma]] as const) {
      expect(validateConfigInput(only({ [key]: { ...c, api_token: "" } }))[`${key}.api_token`]).toBe("Token is required");
    }
  });
  it("accepts an SSH key for GitHub and GitLab only when the server has SSH set up, and only a whole private key", () => {
    const key = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----";
    const ssh: ConnectorInput = { enabled: true, use_server_credentials: false, base_url: "https://api.github.com", auth_method: "ssh_key", ssh_key: key, repositories: ["acme/a"] };
    const available = { github: { credentials_configured: false, ssh_available: true } };
    expect(validateConfigInput(only({ github: ssh }), available)).toEqual({});
    expect(validateConfigInput(only({ github: ssh }))["github.ssh_key"]).toMatch(/not set up/);
    expect(validateConfigInput(only({ github: { ...ssh, ssh_key: "ssh-ed25519 AAAA" } }), available)["github.ssh_key"]).toMatch(/whole private key/);
    expect(validateConfigInput(only({ github: { ...ssh, ssh_key: "" } }), available)["github.ssh_key"]).toBe("Paste the private key");
    expect(validateConfigInput(only({ github: { ...ssh, all_member_projects: true } }), available)["github.all_member_projects"]).toMatch(/needs a token/);
    expect(validateConfigInput(only({ github: { ...ssh, repositories: [] } }), available)["github.repositories"]).toMatch(/Add at least one repository/);
    expect(validateConfigInput(only({ jira: { ...jira, api_token: "", auth_method: "ssh_key", ssh_key: key } }))["jira.api_token"]).toBe("Token is required"); // Jira has no SSH
  });
  it("refuses a connector the server has blocked, and says why", () => {
    const defaults = { figma: { credentials_configured: false, blocked_reason: "Figma waits for the DPIA" } };
    expect(validateConfigInput(only({ figma }), defaults)).toEqual({ "figma.file_keys": "Figma waits for the DPIA" });
    expect(validateConfigInput(only({ figma: off, jira }), defaults)).toEqual({});
  });
});
