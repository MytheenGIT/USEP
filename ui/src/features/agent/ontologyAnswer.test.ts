import { describe, expect, it } from "vitest";
import ontologyFixture from "../../shared/api/fixtures/ontology.json";
import { GraphDto, OntologyDto } from "../../shared/api/types";
import { answerQuestion, SUGGESTED_QUESTIONS } from "./answer";
import { isOntologyQuestion } from "./ontologyAnswer";

const dto = ontologyFixture as unknown as OntologyDto;
const node = (id: string, concept: string, name: string) => ({ id, concept, name, labels: [], properties: {}, source_system: "jira" });
const labelled = (id: string, concept: string, name: string, labels: string[]) => ({ ...node(id, concept, name), labels });
const graph: GraphDto = {
  configuration_id: "c", generated_at: "", ontology_version: "0.1.0",
  nodes: [node("r1", "Requirement", "PAY-1"), labelled("c1", "Change", "PR 7", ["pull_request"]), labelled("c2", "Change", "PR 8", ["pull_request", "hotfix"])],
  edges: [{ id: "e", source: "c1", target: "r1", relation: "implements", confidence: 1 }],
};
const ask = (q: string) => answerQuestion(graph, q, dto);

describe("ontology questions", () => {
  it("define a concept, with how many of it are in this graph", () => {
    const a = ask("What is a Change?");
    expect(a.source).toBe("ontology");
    expect(a.text).toContain("Change:");
    expect(a.text).toContain("In this configuration's graph there are 2.");
    expect(a.concepts).toContain("Change");
    expect(a.citations).toEqual([]);
  });
  it("say what can own a Service, and what a Service can expose", () => {
    expect(ask("What can own a Service?").text).toMatch(/^`owns` allows Team → Service\./);
    expect(ask("What can a Service expose?").text).toMatch(/`exposes` allows Service → API/);
  });
  it("say how two concepts relate, and when they cannot", () => {
    expect(ask("How is a Change related to a Requirement?").text).toContain("implements");
    const none = ask("How is a Team related to an Incident?");
    expect(none.text).toContain("no relationship between Team and Incident");
    expect(none.text).toContain("left out of a graph");
  });
  it("answer yes or no for a specific relationship", () => {
    expect(ask("Can a Team own a Service?").text).toMatch(/^Yes\. The ontology allows `owns` Team → Service/);
    expect(ask("Can a Requirement own a Team?").text).toMatch(/^No\./);
  });
  it("list attributes with where they are defined, and allowed values", () => {
    const a = ask("What attributes does a Service have?");
    expect(a.text).toMatch(/name \(string, required\)/);
    expect(a.text).toMatch(/criticality \(enum[^)]*tier_1\/tier_2\/tier_3/);
    expect(ask("What are the allowed values for criticality?").text).toContain("tier_1, tier_2, tier_3");
  });
  it("describe the hierarchy of a pack concept", () => {
    const sub = dto.concepts.find((c) => c.parent)!;
    expect(ask(`Is ${sub.id} a subclass of something?`).text).toContain(`subclass of ${sub.parent}`);
  });
  it("describe the packs honestly, the policies, the query templates and the domains", () => {
    expect(ask("Which packs are placeholder content?").text).toMatch(/Placeholder content: .*reference/);
    expect(ask("Which packs are placeholder content?").text).toContain("Not signed yet");
    expect(ask("What policies does the ontology have?").text).toMatch(/only tightens access/);
    expect(ask("Which query templates are there?").text).toContain("impact_of_change");
    expect(ask("What domains are there?").text).toMatch(new RegExp(`${dto.domains.length} domains`));
    expect(ask("Which concepts are in the security domain?").text).toMatch(/security domain has \d+ concepts?/);
  });
  it("give an overview of the ontology", () => {
    expect(ask("Give me an overview of the ontology").text).toContain(`${dto.concepts.length} concepts`);
  });
  it("use an organisation word for a concept", () => {
    const withWords: OntologyDto = { ...dto, glossary: { Squad: "Team" } };
    const a = answerQuestion(graph, "What is a squad?", withWords);
    expect(a.concepts).toContain("Team");
    expect(a.text).toContain("also called Squad");
  });
});

describe("routing between the graph and the ontology", () => {
  it("keeps the questions about what is in the graph with the graph", () => {
    for (const q of ["Which requirements have no change implementing them?", "Which incidents were caused by a change?", "Who owns the services?",
      "What changed recently?", "Give me an overview of this knowledge graph"]) {
      expect(isOntologyQuestion(dto, q), q).toBe(false);
      expect(ask(q).source, q).toBe("graph");
    }
  });
  it("every suggested question is answered from the right place", () => {
    const sources = SUGGESTED_QUESTIONS.map((q) => ask(q).source);
    expect(sources.slice(0, 5)).toEqual(["graph", "graph", "graph", "graph", "graph"]);
    expect(sources.slice(5, 8)).toEqual(["ontology", "ontology", "ontology"]);
    expect(sources[8]).toBe("graph");                                  // the label question is about what the graph carries
  });
  it("still answers ontology questions when the graph is empty", () => {
    const empty: GraphDto = { ...graph, nodes: [], edges: [] };
    expect(answerQuestion(empty, "What is a Service?", dto).source).toBe("ontology");
    expect(answerQuestion(empty, "Which incidents were caused by a change?", dto).text).toContain("no nodes yet");
  });
  it("says so when the ontology could not be loaded, and does not guess", () => {
    const a = answerQuestion(graph, "What is a Service?", null);
    expect(a.source).toBe("ontology");
    expect(a.text).toContain("could not be loaded");
  });
  it("does not use the ontology when none is offered (the original behaviour)", () => {
    expect(answerQuestion(graph, "What is a Service?").source).toBe("graph");
  });
  it("says what it can answer for an ontology question it has no shape for", () => {
    expect(ask("Tell me something about concepts of dragons").text).toMatch(/ontology|concepts/);
  });
});

describe("label questions", () => {
  it("say which labels a concept's nodes carry, with counts, and cite the nodes", () => {
    const a = ask("Which labels are on Change?");
    expect(a.text).toContain("pull_request (2)");
    expect(a.text).toContain("hotfix (1)");
    expect(a.source).toBe("graph");
    expect(a.concepts).toEqual(["Change"]);
    expect(a.citations.map((n) => n.id)).toEqual(["c1", "c2"]);
  });
  it("say so when a concept carries none", () => {
    expect(ask("What labels does a Requirement have?").text).toContain("No Requirement node in this graph carries a label");
  });
  it("summarise every label, and add the organisation words when there are some", () => {
    expect(ask("Which labels are used in this graph?").text).toMatch(/Change: pull_request \(2\), hotfix \(1\)/);
    const withWords: OntologyDto = { ...dto, glossary: { Squad: "Team" } };
    expect(answerQuestion(graph, "What labels are there?", withWords).text).toContain("Squad = Team");
  });
  it("work even without an ontology and with an empty graph", () => {
    expect(answerQuestion(graph, "Which labels are used?").text).toContain("pull_request");
    expect(answerQuestion({ ...graph, nodes: [], edges: [] }, "any labels?", dto).text).toContain("No node in this graph carries a label");
  });
});
