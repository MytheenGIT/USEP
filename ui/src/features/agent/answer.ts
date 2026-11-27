import { GraphDto, GraphNodeDto, OntologyDto } from "../../shared/api/types";
import { labelUsage } from "../ontology/ontologyModel";
import { answerFromOntology, isOntologyQuestion, mentioned } from "./ontologyAnswer";

export interface Answer {
  text: string;
  /** Nodes the answer is based on, shown under it so it can be checked against the graph. */
  citations: GraphNodeDto[];
  /** Where the answer comes from: the facts in the graph, or the ontology (the rulebook: definitions, never data). */
  source: "graph" | "ontology";
  /** Ontology answers: the concepts and relationship types it is based on (each concept links to its definition). */
  concepts?: string[];
  relationships?: string[];
}

export const SUGGESTED_QUESTIONS = [
  "Give me an overview of this knowledge graph",
  "Which requirements have no change implementing them?",
  "Which incidents were caused by a change?",
  "Who owns the services?",
  "What changed recently?",
  "What is a Service?",
  "What can own a Service?",
  "How is an Incident related to a Change?",
  "Which labels are used in this graph?",
];

const names = (nodes: GraphNodeDto[], max = 6) => {
  const shown = nodes.slice(0, max).map((n) => n.name).join("; ");
  return nodes.length > max ? `${shown}; and ${nodes.length - max} more` : shown;
};

/**
 * A MOCK-UP of the question-and-answer agent. It answers from two places with fixed question shapes, so the flow can be shown:
 * the graph on screen (what is there) and, when given, the ontology (what can exist and how things may relate). It is not a
 * language model and knows nothing else. `ontology`: undefined = not offered; null = it could not be loaded.
 */
export function answerQuestion(graph: GraphDto, question: string, ontology?: OntologyDto | null): Answer {
  if (ontology !== undefined && isOntologyQuestion(ontology, question)) {
    if (!ontology) return { text: "The ontology could not be loaded right now, so I cannot answer questions about it. I can still answer from the graph.", citations: [], source: "ontology" };
    const o = answerFromOntology(ontology, question, graph);
    return { text: o.text, citations: [], source: "ontology", concepts: o.concepts, relationships: o.relationships };
  }

  const q = question.toLowerCase();
  if (/\blabels?\b/.test(q)) return answerLabels(graph, question, ontology ?? null);
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const of = (concept: string) => graph.nodes.filter((n) => n.concept.toLowerCase() === concept.toLowerCase());
  const edges = (relation: string) => graph.edges.filter((e) => e.relation === relation);

  if (graph.nodes.length === 0) return { text: "This knowledge graph has no nodes yet, so there is nothing to answer from.", citations: [], source: "graph" as const };

  if (/no .*(change|implement)|without|not implemented|unimplemented|missing/.test(q) && /requirement|issue|story/.test(q)) {
    const implemented = new Set(edges("implements").map((e) => e.target));
    const open = of("Requirement").filter((n) => !implemented.has(n.id));
    return open.length
      ? { text: `${open.length} requirement${open.length === 1 ? "" : "s"} ${open.length === 1 ? "has" : "have"} no change implementing ${open.length === 1 ? "it" : "them"} yet: ${names(open)}.`, citations: open.slice(0, 6), source: "graph" as const }
      : { text: "Every requirement in this graph has at least one change that implements it.", citations: of("Requirement").slice(0, 4), source: "graph" as const };
  }

  if (/incident|outage|bug|problem/.test(q)) {
    const incidents = of("Incident");
    const caused = edges("caused_by").filter((e) => byId.get(e.source)?.concept === "Incident");
    if (/cause|because|due to|change/.test(q) && caused.length) {
      const lines = caused.map((e) => `${byId.get(e.source)?.name} was probably caused by ${byId.get(e.target)?.name} (${Math.round(e.confidence * 100)}% sure)`);
      return { text: `${lines.join(". ")}. These links are inferred from the text of the records, so they are marked with a lower confidence.`, citations: caused.flatMap((e) => [byId.get(e.source), byId.get(e.target)]).filter((n): n is GraphNodeDto => !!n).slice(0, 8), source: "graph" as const };
    }
    return incidents.length
      ? { text: `There ${incidents.length === 1 ? "is" : "are"} ${incidents.length} incident${incidents.length === 1 ? "" : "s"}: ${names(incidents)}.`, citations: incidents.slice(0, 6), source: "graph" as const }
      : { text: "No incidents are in this knowledge graph.", citations: [], source: "graph" as const };
  }

  if (/own|owner|team|responsible|who/.test(q)) {
    const owns = edges("owns");
    if (owns.length) {
      const lines = owns.map((e) => `${byId.get(e.source)?.name} owns ${byId.get(e.target)?.name}`);
      return { text: `${lines.join("; ")}.`, citations: owns.flatMap((e) => [byId.get(e.source), byId.get(e.target)]).filter((n): n is GraphNodeDto => !!n).slice(0, 8), source: "graph" as const };
    }
    return { text: "No ownership is recorded in this graph. Ownership comes from the ontology's team and service records, which none of the connected sources provided.", citations: [], source: "graph" as const };
  }

  if (/change|pull request|merge request|deploy|release|recent|commit/.test(q)) {
    const changes = of("Change");
    if (!changes.length) return { text: "No changes are in this knowledge graph. Connect GitLab, GitHub or ServiceNow to bring them in.", citations: [], source: "graph" as const };
    const implemented = edges("implements");
    const lines = changes.slice(0, 4).map((c) => {
      const target = implemented.find((e) => e.source === c.id);
      return target ? `${c.name} implements ${byId.get(target.target)?.name}` : c.name;
    });
    return { text: `${changes.length} change${changes.length === 1 ? "" : "s"} found. ${lines.join("; ")}${changes.length > 4 ? "; and more" : ""}.`, citations: changes.slice(0, 6), source: "graph" as const };
  }

  if (/overview|summar|what.*(graph|know)|describe (this|the) graph/.test(q)) {
    const counts = new Map<string, number>();
    for (const n of graph.nodes) counts.set(n.concept, (counts.get(n.concept) ?? 0) + 1);
    const parts = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([c, k]) => `${k} ${c}${k === 1 ? "" : "s"}`);
    const systems = [...new Set(graph.nodes.map((n) => n.source_system).filter(Boolean))].join(", ");
    return { text: `This graph has ${graph.nodes.length} nodes and ${graph.edges.length} relationships: ${parts.join(", ")}. It was built from ${systems || "the connected sources"}.`, citations: graph.nodes.slice(0, 5), source: "graph" as const };
  }

  const hit = graph.nodes.filter((n) => q.split(/\W+/).some((w) => w.length > 3 && n.name.toLowerCase().includes(w)));
  if (hit.length) {
    const connected = graph.edges.filter((e) => hit.some((h) => h.id === e.source || h.id === e.target)).length;
    return { text: `I found ${hit.length} node${hit.length === 1 ? "" : "s"} that match: ${names(hit)}. ${connected} relationship${connected === 1 ? "" : "s"} touch ${hit.length === 1 ? "it" : "them"}.`, citations: hit.slice(0, 6), source: "graph" as const };
  }
  return { text: "I can answer questions about what is in this knowledge graph: an overview, requirements without a change, incidents and what caused them, who owns what, and recent changes. Try one of the suggestions.", citations: [], source: "graph" as const };
}

/** Labels refine a concept and never replace it. This answers from the labels the graph's nodes carry, plus the ontology's organisation words. */
function answerLabels(graph: GraphDto, question: string, ontology: OntologyDto | null): Answer {
  const q = question.toLowerCase();
  const all = labelUsage(graph);
  const asked = ontology ? mentioned(ontology, q) : [];
  const words = ontology ? Object.entries(ontology.glossary) : [];
  const wordsText = words.length ? ` Organisation words: ${words.map(([w, c]) => `${w} = ${c}`).join(", ")}.` : "";
  if (asked.length) {
    const c = asked[0].id;
    const mine = all.filter((l) => l.concept === c);
    return {
      text: mine.length ? `${c} nodes carry these labels: ${mine.map((l) => `${l.label} (${l.count})`).join(", ")}.${wordsText}` : `No ${c} node in this graph carries a label.${wordsText}`,
      citations: graph.nodes.filter((n) => n.concept === c && n.labels.length).slice(0, 6), source: "graph", concepts: [c],
    };
  }
  if (all.length === 0) return { text: `No node in this graph carries a label.${wordsText}`, citations: [], source: "graph" };
  const byConcept = new Map<string, string[]>();
  for (const l of all) byConcept.set(l.concept, [...(byConcept.get(l.concept) ?? []), `${l.label} (${l.count})`]);
  return {
    text: `Labels in this graph: ${[...byConcept.entries()].map(([c, ls]) => `${c}: ${ls.join(", ")}`).join("; ")}. A label refines a concept; it never replaces it.${wordsText}`,
    citations: graph.nodes.filter((n) => n.labels.length).slice(0, 6), source: "graph", concepts: [...byConcept.keys()],
  };
}
