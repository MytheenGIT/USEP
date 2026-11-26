import { describe, expect, it } from "vitest";
import { mockApi, MOCK_PASSWORD, MOCK_USER, PROCESSING_MS } from "./api/mock";
import { emptyConfig, validateConfig, validateUrl } from "./validation";

const ok = {
  name: "Pay", git_url: "https://github.com/acme/checkout", jira_url: "https://acme.atlassian.net/jira",
  confluence_url: "https://acme.atlassian.net/wiki", figma_url: "https://www.figma.com/file/abc", ad_url: "ldaps://dc01.corp.example.com",
};

describe("validation", () => {
  it("accepts a complete configuration", () => expect(validateConfig(ok)).toEqual({}));
  it("requires every field except the AD URL", () => expect(Object.keys(validateConfig(emptyConfig())).sort()).toEqual(["confluence_url", "figma_url", "git_url", "jira_url", "name"]));
  it("accepts an empty AD URL but checks it when given", () => { expect(validateConfig({ ...ok, ad_url: "" })).toEqual({}); expect(validateConfig({ ...ok, ad_url: "http://x.example.com" }).ad_url).toBeTruthy(); });
  it("allows ldaps only for the AD URL", () => { expect(validateConfig({ ...ok, ad_url: "https://adfs.example.com" })).toEqual({}); expect(validateConfig({ ...ok, ad_url: "ldap://dc01.corp.example.com" }).ad_url).toBeTruthy(); expect(validateConfig({ ...ok, git_url: "ldaps://x.example.com" }).git_url).toBeTruthy(); });
  it.each(["http://a.com/x", "ftp://a.com", "not a url", "https://user:pw@a.com/x", "https://localhost/x", "javascript:alert(1)"])("rejects %s", (u) => expect(validateUrl(u)).not.toBe(""));
  it("checks every URL", () => expect(validateConfig({ ...ok, jira_url: "http://x.com" }).jira_url).toBeTruthy());
  it("limits the name length", () => expect(validateConfig({ ...ok, name: "x".repeat(81) }).name).toBeTruthy());
});

describe("mock api flow", () => {
  it("rejects bad credentials and unauthenticated calls", async () => {
    await expect(mockApi.login("admin", "wrong")).rejects.toMatchObject({ status: 401 });
    await expect(mockApi.listConfigurations("nope")).rejects.toMatchObject({ status: 401 });
  });
  it("creates a configuration, processes it, then serves a graph", async () => {
    const { token } = await mockApi.login(MOCK_USER, MOCK_PASSWORD);
    await expect(mockApi.createConfiguration(token, emptyConfig())).rejects.toMatchObject({ status: 422 });
    const c = await mockApi.createConfiguration(token, ok);
    expect(c.status).toBe("processing");
    await expect(mockApi.getGraph(token, c.id)).rejects.toMatchObject({ status: 409 });
    await new Promise((r) => setTimeout(r, PROCESSING_MS + 100));
    const g = await mockApi.getGraph(token, c.id);
    expect(g.nodes.length).toBeGreaterThan(5);
    const ids = new Set(g.nodes.map((n) => n.id));
    expect(g.edges.every((e) => ids.has(e.source) && ids.has(e.target))).toBe(true);
    await mockApi.logout(token);
    await expect(mockApi.getGraph(token, c.id)).rejects.toMatchObject({ status: 401 });
  });
});
