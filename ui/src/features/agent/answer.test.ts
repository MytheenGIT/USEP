import { describe, expect, it } from "vitest";
import { GraphDto } from "../../shared/api/types";
import { answerQuestion } from "./answer";

const node = (id: string, concept: string, name: string, source_system = "jira") => ({ id, concept, name, labels: [], properties: {}, source_system });
const edge = (source: string, relation: string, target: string, confidence = 1) => ({ id: `${source}-${relation}-${target}`, source, target, relation, confidence });

const graph: GraphDto = {
  configuration_id: "c", generated_at: "", ontology_version: "0.1.0",
  nodes: [
    node("t", "Team", "payments-team", "architecture"), node("s", "Service", "checkout", "gitlab"),
    node("r1", "Requirement", "PAY-1 retry"), node("r2", "Requirement", "PAY-2 receipts"),
    node("c1", "Change", "PR 7 add retry", "github"), node("i1", "Incident", "INC1 timeouts", "servicenow"),
  ],
  edges: [edge("t", "owns", "s"), edge("c1", "implements", "r1"), edge("i1", "caused_by", "c1", 0.6)],
};

describe("answerQuestion (the agent mock-up)", () => {
  it("lists requirements nothing implements, and cites them", () => {
    const a = answerQuestion(graph, "Which requirements have no change implementing them?");
    expect(a.text).toContain("PAY-2 receipts");
    expect(a.text).not.toContain("PAY-1 retry");
    expect(a.citations.map((n) => n.id)).toEqual(["r2"]);
  });
  it("says what caused an incident, with the confidence", () => {
    const a = answerQuestion(graph, "Which incidents were caused by a change?");
    expect(a.text).toContain("INC1 timeouts was probably caused by PR 7 add retry (60% sure)");
    expect(a.citations.map((n) => n.id).sort()).toEqual(["c1", "i1"]);
  });
  it("answers who owns what from the ownership edges", () => {
    expect(answerQuestion(graph, "Who owns the services?").text).toBe("payments-team owns checkout.");
  });
  it("describes recent changes and what they implement", () => {
    expect(answerQuestion(graph, "What changed recently?").text).toContain("PR 7 add retry implements PAY-1 retry");
  });
  it("gives an overview with counts and sources", () => {
    const a = answerQuestion(graph, "Give me an overview of this knowledge graph");
    expect(a.text).toContain("6 nodes and 3 relationships");
    expect(a.text).toContain("2 Requirements");
    expect(a.text).toContain("architecture, gitlab, jira, github, servicenow");
  });
  it("finds a node by a word in its name", () => {
    expect(answerQuestion(graph, "tell me about checkout").citations.map((n) => n.id)).toEqual(["s"]);
  });
  it("does not make things up: it says what it can answer, and handles an empty graph", () => {
    expect(answerQuestion(graph, "what is the meaning of life").text).toContain("Try one of the suggestions");
    expect(answerQuestion({ ...graph, nodes: [], edges: [] }, "overview").text).toContain("no nodes yet");
    expect(answerQuestion({ ...graph, edges: [] }, "who owns the services?").text).toContain("No ownership is recorded");
  });
});
