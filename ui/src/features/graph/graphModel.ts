import { GraphDto, GraphEdgeDto, GraphNodeDto } from "../../shared/api/types";

export interface GraphFilter {
  search: string;
  hiddenConcepts: ReadonlySet<string>;
}

export interface VisibleGraph {
  nodes: GraphNodeDto[];
  edges: GraphEdgeDto[];
}

export const conceptsOf = (graph: GraphDto): string[] => [...new Set(graph.nodes.map((n) => n.concept))].sort();

/** Nodes matching the search and not hidden by concept; edges only when both ends are visible. */
export function filterGraph(graph: GraphDto, filter: GraphFilter): VisibleGraph {
  const q = filter.search.trim().toLowerCase();
  const nodes = graph.nodes.filter(
    (n) => !filter.hiddenConcepts.has(n.concept) && (!q || n.name.toLowerCase().includes(q) || n.concept.toLowerCase().includes(q)),
  );
  const ids = new Set(nodes.map((n) => n.id));
  return { nodes, edges: graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target)) };
}

export const edgesOf = (graph: GraphDto, nodeId: string): GraphEdgeDto[] =>
  graph.edges.filter((e) => e.source === nodeId || e.target === nodeId);

export const nameOf = (graph: GraphDto, id: string): string => graph.nodes.find((n) => n.id === id)?.name ?? id;

export function toggle<T>(set: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}
