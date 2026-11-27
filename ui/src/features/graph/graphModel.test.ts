import { describe, expect, it } from "vitest";
import { GraphDto } from "../../shared/api/types";
import { conceptsOf, edgesOf, filterGraph, toggle } from "./graphModel";

const node = (id: string, concept: string, name: string) => ({ id, concept, name, labels: [], properties: {} });
const graph: GraphDto = {
  configuration_id: "c", generated_at: "2026-11-25T00:00:00.000Z", ontology_version: "0.1.0",
  nodes: [node("a", "Service", "checkout"), node("b", "Requirement", "PAY-12 retry"), node("c", "Team", "payments")],
  edges: [
    { id: "e1", source: "a", target: "b", relation: "implements", confidence: 1 },
    { id: "e2", source: "c", target: "a", relation: "owns", confidence: 1 },
  ],
};

describe("graphModel", () => {
  it("lists concepts once, sorted", () => {
    expect(conceptsOf(graph)).toEqual(["Requirement", "Service", "Team"]);
  });
  it("filters by search on name or concept", () => {
    expect(filterGraph(graph, { search: "pay-12", hiddenConcepts: new Set() }).nodes.map((n) => n.id)).toEqual(["b"]);
    expect(filterGraph(graph, { search: "team", hiddenConcepts: new Set() }).nodes.map((n) => n.id)).toEqual(["c"]);
  });
  it("drops edges whose endpoint is hidden", () => {
    const v = filterGraph(graph, { search: "", hiddenConcepts: new Set(["Team"]) });
    expect(v.nodes).toHaveLength(2);
    expect(v.edges.map((e) => e.id)).toEqual(["e1"]);
  });
  it("finds the edges of a node and toggles sets immutably", () => {
    expect(edgesOf(graph, "a")).toHaveLength(2);
    const base = new Set(["x"]);
    expect([...toggle(base, "y")]).toEqual(["x", "y"]);
    expect([...toggle(base, "x")]).toEqual([]);
    expect([...base]).toEqual(["x"]);
  });
});
