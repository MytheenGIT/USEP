import { GraphDto, GraphifyGraph, OntologyConcept, OntologyDto, OntologyPin, OntologyRelationship } from "../../shared/api/types";

/** Honest-status messages: placeholder (reference-only) and unsigned content must always look like it. */
export function statusBanners(dto: OntologyDto): string[] {
  const out: string[] = [];
  const ref = dto.packs.filter((p) => p.reference_only).map((p) => p.id);
  if (ref.length) out.push(`Placeholder content: ${ref.join(", ")} ${ref.length === 1 ? "is a" : "are"} reference-only example${ref.length === 1 ? "" : "s"}, not real client definitions.`);
  const unsigned = dto.packs.filter((p) => !p.signed).map((p) => p.id);
  if (unsigned.length) out.push(`Unsigned: ${unsigned.join(", ")} ${unsigned.length === 1 ? "has" : "have"} no signature yet (registry signing is not live).`);
  return out;
}

/** Words an organisation uses for a concept ("Squad" for Team). Shown next to the concept, never instead of it. */
export function glossaryWordsFor(dto: OntologyDto, concept: string): string[] {
  return Object.entries(dto.glossary).filter(([, c]) => c === concept).map(([w]) => w).sort();
}

/** Concepts grouped by domain (concepts with no domain go last), filtered by id, description or glossary word. */
export function conceptsByDomain(dto: OntologyDto, query: string): { domain: string; concepts: OntologyConcept[] }[] {
  const q = query.trim().toLowerCase();
  const match = (c: OntologyConcept) =>
    !q || c.id.toLowerCase().includes(q) || c.description.toLowerCase().includes(q) || glossaryWordsFor(dto, c.id).some((w) => w.toLowerCase().includes(q));
  const groups = new Map<string, OntologyConcept[]>();
  for (const c of dto.concepts.filter(match)) {
    const d = c.domain ?? "(no domain)";
    groups.set(d, [...(groups.get(d) ?? []), c]);
  }
  const order = [...dto.domains, "(no domain)"];
  return [...groups.entries()].sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0])).map(([domain, concepts]) => ({ domain, concepts }));
}

export function relationshipsOf(dto: OntologyDto, concept: string): { outgoing: OntologyRelationship[]; incoming: OntologyRelationship[] } {
  return {
    outgoing: dto.relationships.filter((r) => r.from.includes(concept)),
    incoming: dto.relationships.filter((r) => r.to.includes(concept)),
  };
}

export function allowedValues(dto: OntologyDto, valuesRef: string | null): string[] | null {
  return valuesRef ? dto.vocabularies[valuesRef] ?? null : null;
}

/** Cytoscape elements for the type diagram, read from the Graphify graph. One edge per (relation, from, to). */
export function typeGraphElements(g: GraphifyGraph) {
  const ids = new Set(g.nodes.map((n) => n.id));
  return [
    ...g.nodes.map((n) => ({ data: { id: n.id, label: n.label } })),
    ...g.links
      .filter((l) => ids.has(l.source) && ids.has(l.target))
      .map((l, i) => ({ data: { id: `${l.relation}:${l.source}:${l.target}:${i}`, source: l.source, target: l.target, label: l.relation, isa: l.relation === "is_a" ? 1 : 0 } })),
  ];
}

/** Structural check of a server answer before the console trusts it. Returns the problems found (empty = fine). */
export function ontologyProblems(x: unknown): string[] {
  const d = x as Partial<OntologyDto> | null;
  if (!d || typeof d !== "object") return ["not an object"];
  const p: string[] = [];
  if (typeof d.ontology_version !== "string") p.push("ontology_version");
  if (typeof d.digest !== "string" || d.digest.length < 12) p.push("digest");
  for (const k of ["packs", "domains", "concepts", "relationships", "templates", "policies"] as const) if (!Array.isArray(d[k])) p.push(k);
  for (const k of ["vocabularies", "glossary"] as const) if (!d[k] || typeof d[k] !== "object") p.push(k);
  const ids = new Set((d.concepts ?? []).map((c) => c.id));
  for (const c of d.concepts ?? []) {
    if (c.parent && !ids.has(c.parent)) p.push(`concept ${c.id}: unknown parent ${c.parent}`);
    for (const a of c.attributes ?? []) if (!a.defined_in || !ids.has(a.defined_in)) p.push(`${c.id}.${a.name}: defined_in`);
  }
  for (const r of d.relationships ?? []) for (const e of [...r.from, ...r.to]) if (!ids.has(e)) p.push(`relationship ${r.id}: unknown concept ${e}`);
  for (const pol of d.policies ?? []) if (!["deny", "require_approval", "restrict_to_owners"].includes(pol.effect)) p.push(`policy ${pol.id}: effect ${pol.effect}`);
  return p;
}

/** How much of each concept and relationship type this configuration's knowledge graph actually uses. */
export function usageCounts(graph: GraphDto | null): { concepts: Record<string, number>; relations: Record<string, number> } {
  const concepts: Record<string, number> = {};
  const relations: Record<string, number> = {};
  for (const n of graph?.nodes ?? []) concepts[n.concept] = (concepts[n.concept] ?? 0) + 1;
  for (const e of graph?.edges ?? []) relations[e.relation] = (relations[e.relation] ?? 0) + 1;
  return { concepts, relations };
}

/** Says when the ontology on screen is not the one the configuration's graph was checked against (null when they match). */
export function driftMessage(pin: OntologyPin | null | undefined, dto: OntologyDto): string | null {
  if (!pin) return null;
  if (pin.digest === dto.digest) return null;
  return `The ontology changed since this configuration's graph was built (built with ${pin.version}, digest ${pin.digest.slice(0, 12)}; now ${dto.ontology_version}, digest ${dto.digest.slice(0, 12)}). Submit the configuration again to rebuild the graph against the current ontology.`;
}

export interface LabelUse { concept: string; label: string; count: number; }

/** The labels this configuration's graph carries, per concept, with how many nodes carry each. A label refines a concept, never replaces it. */
export function labelUsage(graph: GraphDto | null): LabelUse[] {
  const counts = new Map<string, LabelUse>();
  for (const n of graph?.nodes ?? []) {
    for (const label of n.labels) {
      const k = `${n.concept}\u0000${label}`;
      const cur = counts.get(k);
      if (cur) cur.count += 1; else counts.set(k, { concept: n.concept, label, count: 1 });
    }
  }
  return [...counts.values()].sort((a, b) => a.concept.localeCompare(b.concept) || b.count - a.count || a.label.localeCompare(b.label));
}
