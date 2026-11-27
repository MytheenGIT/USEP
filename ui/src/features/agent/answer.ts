import { GraphDto, GraphNodeDto } from "../../shared/api/types";

export interface Answer {
  text: string;
  /** Nodes the answer is based on, shown under it so it can be checked against the graph. */
  citations: GraphNodeDto[];
}

export const SUGGESTED_QUESTIONS = [
  "Give me an overview of this knowledge graph",
  "Which requirements have no change implementing them?",
  "Which incidents were caused by a change?",
  "Who owns the services?",
  "What changed recently?",
];

const names = (nodes: GraphNodeDto[], max = 6) => {
  const shown = nodes.slice(0, max).map((n) => n.name).join("; ");
  return nodes.length > max ? `${shown}; and ${nodes.length - max} more` : shown;
};

/**
 * A MOCK-UP of the question-and-answer agent. It answers from the graph on screen with a few fixed question shapes, so the
 * flow can be shown; it is not a language model and knows nothing outside the graph.
 */
export function answerQuestion(graph: GraphDto, question: string): Answer {
  const q = question.toLowerCase();
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const of = (concept: string) => graph.nodes.filter((n) => n.concept.toLowerCase() === concept.toLowerCase());
  const edges = (relation: string) => graph.edges.filter((e) => e.relation === relation);

  if (graph.nodes.length === 0) return { text: "This knowledge graph has no nodes yet, so there is nothing to answer from.", citations: [] };

  if (/no .*(change|implement)|without|not implemented|unimplemented|missing/.test(q) && /requirement|issue|story/.test(q)) {
    const implemented = new Set(edges("implements").map((e) => e.target));
    const open = of("Requirement").filter((n) => !implemented.has(n.id));
    return open.length
      ? { text: `${open.length} requirement${open.length === 1 ? "" : "s"} ${open.length === 1 ? "has" : "have"} no change implementing ${open.length === 1 ? "it" : "them"} yet: ${names(open)}.`, citations: open.slice(0, 6) }
      : { text: "Every requirement in this graph has at least one change that implements it.", citations: of("Requirement").slice(0, 4) };
  }

  if (/incident|outage|bug|problem/.test(q)) {
    const incidents = of("Incident");
    const caused = edges("caused_by").filter((e) => byId.get(e.source)?.concept === "Incident");
    if (/cause|because|due to|change/.test(q) && caused.length) {
      const lines = caused.map((e) => `${byId.get(e.source)?.name} was probably caused by ${byId.get(e.target)?.name} (${Math.round(e.confidence * 100)}% sure)`);
      return { text: `${lines.join(". ")}. These links are inferred from the text of the records, so they are marked with a lower confidence.`, citations: caused.flatMap((e) => [byId.get(e.source), byId.get(e.target)]).filter((n): n is GraphNodeDto => !!n).slice(0, 8) };
    }
    return incidents.length
      ? { text: `There ${incidents.length === 1 ? "is" : "are"} ${incidents.length} incident${incidents.length === 1 ? "" : "s"}: ${names(incidents)}.`, citations: incidents.slice(0, 6) }
      : { text: "No incidents are in this knowledge graph.", citations: [] };
  }

  if (/own|owner|team|responsible|who/.test(q)) {
    const owns = edges("owns");
    if (owns.length) {
      const lines = owns.map((e) => `${byId.get(e.source)?.name} owns ${byId.get(e.target)?.name}`);
      return { text: `${lines.join("; ")}.`, citations: owns.flatMap((e) => [byId.get(e.source), byId.get(e.target)]).filter((n): n is GraphNodeDto => !!n).slice(0, 8) };
    }
    return { text: "No ownership is recorded in this graph. Ownership comes from the ontology's team and service records, which none of the connected sources provided.", citations: [] };
  }

  if (/change|pull request|merge request|deploy|release|recent|commit/.test(q)) {
    const changes = of("Change");
    if (!changes.length) return { text: "No changes are in this knowledge graph. Connect GitLab, GitHub or ServiceNow to bring them in.", citations: [] };
    const implemented = edges("implements");
    const lines = changes.slice(0, 4).map((c) => {
      const target = implemented.find((e) => e.source === c.id);
      return target ? `${c.name} implements ${byId.get(target.target)?.name}` : c.name;
    });
    return { text: `${changes.length} change${changes.length === 1 ? "" : "s"} found. ${lines.join("; ")}${changes.length > 4 ? "; and more" : ""}.`, citations: changes.slice(0, 6) };
  }

  if (/overview|summar|what.*(graph|know)|describe (this|the) graph/.test(q)) {
    const counts = new Map<string, number>();
    for (const n of graph.nodes) counts.set(n.concept, (counts.get(n.concept) ?? 0) + 1);
    const parts = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([c, k]) => `${k} ${c}${k === 1 ? "" : "s"}`);
    const systems = [...new Set(graph.nodes.map((n) => n.source_system).filter(Boolean))].join(", ");
    return { text: `This graph has ${graph.nodes.length} nodes and ${graph.edges.length} relationships: ${parts.join(", ")}. It was built from ${systems || "the connected sources"}.`, citations: graph.nodes.slice(0, 5) };
  }

  const hit = graph.nodes.filter((n) => q.split(/\W+/).some((w) => w.length > 3 && n.name.toLowerCase().includes(w)));
  if (hit.length) {
    const connected = graph.edges.filter((e) => hit.some((h) => h.id === e.source || h.id === e.target)).length;
    return { text: `I found ${hit.length} node${hit.length === 1 ? "" : "s"} that match: ${names(hit)}. ${connected} relationship${connected === 1 ? "" : "s"} touch ${hit.length === 1 ? "it" : "them"}.`, citations: hit.slice(0, 6) };
  }
  return { text: "I can answer questions about what is in this knowledge graph: an overview, requirements without a change, incidents and what caused them, who owns what, and recent changes. Try one of the suggestions.", citations: [] };
}
