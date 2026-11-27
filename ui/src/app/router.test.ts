import { describe, expect, it } from "vitest";
import { parseRoute } from "./router";

describe("parseRoute", () => {
  it("defaults to the configuration list", () => {
    expect(parseRoute("")).toEqual({ name: "configurations" });
    expect(parseRoute("#/configurations")).toEqual({ name: "configurations" });
  });
  it("parses the processing, agent and profile routes", () => {
    expect(parseRoute("#/configurations/abc/processing")).toEqual({ name: "processing", id: "abc" });
    expect(parseRoute("#/configurations/abc/add")).toEqual({ name: "add", id: "abc" });
    expect(parseRoute("#/agent")).toEqual({ name: "agent" });
    expect(parseRoute("#/agent/abc")).toEqual({ name: "agent", id: "abc" });
    expect(parseRoute("#/profile")).toEqual({ name: "profile" });
    expect(parseRoute("#/agent/a/b")).toEqual({ name: "notfound" });
  });
  it("parses detail and graph routes", () => {
    expect(parseRoute("#/configurations/abc")).toEqual({ name: "configuration", id: "abc" });
    expect(parseRoute("#/configurations/abc/graph")).toEqual({ name: "graph", id: "abc" });
  });
  it("parses the new-configuration route with an optional template", () => {
    expect(parseRoute("#/configurations/new")).toEqual({ name: "new" });
    expect(parseRoute("#/configurations/new?from=abc")).toEqual({ name: "new", from: "abc" });
  });
  it("flags unknown routes", () => {
    expect(parseRoute("#/nope/1/2/3")).toEqual({ name: "notfound" });
  });
});
