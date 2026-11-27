import { GraphDto, OntologyConcept, OntologyDto } from "../../shared/api/types";
import { allowedValues, glossaryWordsFor, relationshipsOf, usageCounts } from "../ontology/ontologyModel";

/** What an ontology answer is based on: concepts (each links to its definition) and relationship types. */
export interface OntologyAnswer {
  text: string;
  concepts: string[];
  relationships: string[];
}

const words = (id: string) => id.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();       // DataAsset -> data asset
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const list = (xs: string[], max = 8) => (xs.length > max ? `${xs.slice(0, max).join(", ")} and ${xs.length - max} more` : xs.join(", "));
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Signals that a question is about the ontology (the rulebook) rather than about what is in the graph. */
const ONTOLOGY_CUES = /\bontolog|\bconcepts?\b|relationship types?|\battributes?\b|vocabular|\bpacks?\b|\bpolic(y|ies)\b|\btemplates?\b|\bdomains?\b|allowed|\bdefine\b|\bmeaning\b|subclass|\bproperties of\b|fan-?out/;
const DEFINITION_CUES = /what (is|are) (a |an |the )?|what does .* mean|explain|tell me about|describe|what can\b|who can\b|can (a |an |the )?\w+ \w+|how (is|are|do|does) .*(relat|connect|link)|related to|between/;

export function isOntologyQuestion(dto: OntologyDto | null, question: string): boolean {
  const q = question.toLowerCase();
  if (ONTOLOGY_CUES.test(q)) return true;
  // Without the ontology we cannot see concept names, so only shapes that are about the rulebook and never about graph facts count.
  if (!dto) return /^what (is|are) (a |an |the )?[a-z ]{2,30}\??$/.test(q) || /^(what|who) can\b|^can (a |an |the )\w+ \w+|how (is|are) .*related/.test(q);
  return mentioned(dto, q).length > 0 && DEFINITION_CUES.test(q) && !/\b(in|from) this (graph|configuration)\b/.test(q);
}

/** Concepts named in the text (by id, spaced id, plural, or an organisation word), in the order they appear. */
export function mentioned(dto: OntologyDto, q: string): OntologyConcept[] {
  const found: { c: OntologyConcept; at: number }[] = [];
  for (const c of dto.concepts) {
    const variants = [c.id.toLowerCase(), words(c.id), ...glossaryWordsFor(dto, c.id).map((w) => w.toLowerCase())];
    for (const v of new Set(variants)) {
      const m = new RegExp(`\\b${esc(v)}(s|es)?\\b`).exec(q);
      if (m) { found.push({ c, at: m.index }); break; }
    }
  }
  return found.sort((a, b) => a.at - b.at).map((f) => f.c);
}

const ancestors = (dto: OntologyDto, id: string): string[] => {
  const out: string[] = [];
  for (let c = dto.concepts.find((x) => x.id === id); c && !out.includes(c.id); c = c.parent ? dto.concepts.find((x) => x.id === c!.parent) : undefined) out.push(c.id);
  return out;
};
const children = (dto: OntologyDto, id: string) => dto.concepts.filter((c) => c.parent === id).map((c) => c.id);

/** Relationship types the ontology allows from `a` to `b` (a subclass counts as its parent). */
function between(dto: OntologyDto, a: string, b: string) {
  const A = ancestors(dto, a), B = ancestors(dto, b);
  return dto.relationships.filter((r) => A.some((x) => r.from.includes(x)) && B.some((x) => r.to.includes(x)));
}

/** A relationship type named in the question by its verb ("own" for owns, "caused" for caused_by), not counting concept names. */
function relationNamed(dto: OntologyDto, q: string, concepts: OntologyConcept[]) {
  const skip = new Set(concepts.flatMap((c) => [c.id.toLowerCase(), ...words(c.id).split(" ")]));
  const tokens = [...q.matchAll(/[a-z]+/g)].map((m) => ({ t: m[0], at: m.index ?? 0 })).filter((x) => !skip.has(x.t) && x.t.length >= 3);
  for (const r of dto.relationships) {
    const first = r.id.split("_")[0];
    const stem = first.replace(/(es|s|ed)$/, "");
    const hit = tokens.find((x) => x.t === r.id || x.t.startsWith(stem.length >= 3 ? stem : first));
    if (hit && !["test", "tests"].includes(hit.t)) return { rel: r, at: hit.at };
  }
  return null;
}

export function answerFromOntology(dto: OntologyDto, question: string, graph: GraphDto | null): OntologyAnswer {
  const q = question.toLowerCase();
  const cs = mentioned(dto, q);
  const used = usageCounts(graph);
  const none = (text: string): OntologyAnswer => ({ text, concepts: [], relationships: [] });

  // Policies, query templates, packs, vocabularies, domains: questions with no concept in them.
  if (/\bpolic(y|ies)\b|tighten|require approval|\bdeny\b/.test(q) && cs.length === 0) {
    return { text: `The ontology has ${plural(dto.policies.length, "policy", "policies")}, and each one only tightens access: ${dto.policies.map((p) => `${p.id} (${p.effect.replace(/_/g, " ")})`).join("; ")}. A pack can never grant access.`, concepts: [], relationships: [] };
  }
  if (/\btemplates?\b|named quer|fan-?out|max depth/.test(q)) {
    return { text: `There ${dto.templates.length === 1 ? "is" : "are"} ${plural(dto.templates.length, "named query template")}: ${dto.templates.map((t) => `${t.name} (depth ≤ ${t.max_depth}, fan-out ≤ ${t.fanout_cap}${t.pack_id === "core" ? "" : `, from ${t.pack_id}`})`).join("; ")}. Every one filters on the tenant and applies the access check inside the match.`, concepts: [], relationships: [] };
  }
  if (/\bpacks?\b|placeholder|reference|signed|unsigned|digest|version/.test(q) && cs.length === 0) {
    const ph = dto.packs.filter((p) => p.reference_only).map((p) => p.id), un = dto.packs.filter((p) => !p.signed).map((p) => p.id);
    return { text: `Core ${dto.ontology_version} with ${plural(dto.packs.length - 1, "pack")} on top (${dto.packs.map((p) => `${p.id}@${p.version}`).join(", ")}). ${ph.length ? `Placeholder content: ${list(ph)}. ` : ""}${un.length ? `Not signed yet: ${list(un)}. ` : "All packs are signed. "}Digest ${dto.digest.slice(0, 12)}, which changes whenever any definition changes.`, concepts: [], relationships: [] };
  }
  const attrName = dto.concepts.flatMap((c) => c.attributes).find((a) => new RegExp(`\\b(${esc(a.name)}|${esc(a.name.replace(/_/g, " "))})\\b`).test(q));
  if (/allowed values?|values? (of|for)|vocabular|options? (for|of)|which values/.test(q) || (attrName?.values_ref && cs.length === 0)) {
    const vocab = Object.keys(dto.vocabularies).find((v) => q.includes(v.toLowerCase().replace(/_/g, " ")) || q.includes(v.toLowerCase()));
    const ref = attrName?.values_ref ?? vocab ?? null;
    const vals = ref ? allowedValues(dto, ref) : null;
    if (vals) return { text: `${attrName ? `${attrName.name} (on ${dto.concepts.filter((c) => c.attributes.some((a) => a.name === attrName.name)).map((c) => c.id).join(", ")})` : ref} takes one of: ${vals.join(", ")}.`, concepts: [], relationships: [] };
    return { text: `The controlled lists are: ${Object.keys(dto.vocabularies).join(", ")}. Name one, or an attribute such as criticality, and I will list its values.`, concepts: [], relationships: [] };
  }
  if (/\bdomains?\b/.test(q) && cs.length === 0) {
    const named = dto.domains.find((d) => q.includes(d));
    if (named) { const inD = dto.concepts.filter((c) => c.domain === named).map((c) => c.id); return { text: `The ${named} domain has ${plural(inD.length, "concept")}: ${list(inD, 12)}.`, concepts: inD.slice(0, 8), relationships: [] }; }
    return none(`The ontology groups its ${dto.concepts.length} concepts into ${dto.domains.length} domains: ${dto.domains.map((d) => `${d} (${dto.concepts.filter((c) => c.domain === d).length})`).join(", ")}.`);
  }
  if (cs.length === 0 && /relationship types?|relationships|\bhow many\b/.test(q) && /ontology|types?|list|which|what/.test(q)) {
    return { text: `The ontology defines ${plural(dto.relationships.length, "relationship type")}: ${dto.relationships.map((r) => r.id).join(", ")}. Ask how two concepts relate, for example Incident and Change.`, concepts: [], relationships: dto.relationships.map((r) => r.id).slice(0, 8) };
  }
  if (cs.length === 0 && /\bconcepts?\b|which kinds|what kinds|what can exist/.test(q)) {
    return none(`The ontology has ${plural(dto.concepts.length, "concept")} in ${dto.domains.length} domains: ${list(dto.concepts.map((c) => c.id), 18)}. Ask "What is a Service?" for any of them.`);
  }

  // Questions about one or two concepts.
  const rel = relationNamed(dto, q, cs);
  if (cs.length >= 2) {
    const [a, b] = cs.slice(0, 2);
    const ab = between(dto, a.id, b.id), ba = between(dto, b.id, a.id);
    if (rel) {
      const ok = [...ab, ...ba].some((r) => r.id === rel.rel.id);
      const dir = ab.some((r) => r.id === rel.rel.id) ? `${a.id} → ${b.id}` : `${b.id} → ${a.id}`;
      return ok
        ? { text: `Yes. The ontology allows \`${rel.rel.id}\` ${dir}.`, concepts: [a.id, b.id], relationships: [rel.rel.id] }
        : { text: `No. \`${rel.rel.id}\` runs ${list(rel.rel.from)} → ${list(rel.rel.to)}, so it is not allowed between ${a.id} and ${b.id}. A link like that would be left out of a graph.`, concepts: [a.id, b.id], relationships: [rel.rel.id] };
    }
    if (!ab.length && !ba.length) return { text: `The ontology has no relationship between ${a.id} and ${b.id} in either direction, so a link between them would be left out of a graph.`, concepts: [a.id, b.id], relationships: [] };
    const part = (from: string, to: string, rs: typeof ab) => (rs.length ? `${from} → ${to}: ${rs.map((r) => r.id).join(", ")}` : "");
    return { text: `Allowed relationships — ${[part(a.id, b.id, ab), part(b.id, a.id, ba)].filter(Boolean).join("; ")}.`, concepts: [a.id, b.id], relationships: [...ab, ...ba].map((r) => r.id) };
  }
  if (cs.length === 1) {
    const c = cs[0];
    const asSubject = rel ? rel.at > (new RegExp(`\\b${esc(c.id.toLowerCase())}`).exec(q)?.index ?? 0) : false;   // "what can a Service expose" vs "what can own a Service"
    if (rel) {
      const r = rel.rel;
      const mine = ancestors(dto, c.id);
      if (asSubject && mine.some((x) => r.from.includes(x))) return { text: `\`${r.id}\` allows ${c.id} → ${list(r.to)}.`, concepts: [c.id, ...r.to.slice(0, 5)], relationships: [r.id] };
      if (mine.some((x) => r.to.includes(x))) return { text: `\`${r.id}\` allows ${list(r.from)} → ${c.id}.`, concepts: [c.id, ...r.from.slice(0, 5)], relationships: [r.id] };
      if (mine.some((x) => r.from.includes(x))) return { text: `\`${r.id}\` allows ${c.id} → ${list(r.to)}.`, concepts: [c.id, ...r.to.slice(0, 5)], relationships: [r.id] };
      return { text: `\`${r.id}\` does not involve ${c.id}: it runs ${list(r.from)} → ${list(r.to)}.`, concepts: [c.id], relationships: [r.id] };
    }
    if (/attribute|propert|field|required|what does .* have/.test(q)) {
      const attrs = c.attributes;
      return { text: `${c.id} has ${plural(attrs.length, "attribute")}: ${attrs.map((a) => `${a.name} (${a.type}${a.required ? ", required" : ""}${a.multi ? ", many" : ""}${a.defined_in !== c.id ? `, from ${a.defined_in}` : ""}${a.values_ref ? `, one of ${(allowedValues(dto, a.values_ref) ?? []).join("/")}` : ""})`).join("; ")}.`, concepts: [c.id], relationships: [] };
    }
    if (/subclass|parent|extends|child|kind of/.test(q)) {
      const kids = children(dto, c.id);
      return { text: `${c.id} ${c.parent ? `is a subclass of ${c.parent}` : "is a core concept"}${kids.length ? `, and ${list(kids)} ${kids.length === 1 ? "is its subclass" : "are its subclasses"}` : ""}.`, concepts: [c.id, ...(c.parent ? [c.parent] : []), ...kids].slice(0, 6), relationships: [] };
    }
    if (/relat|connect|link|between/.test(q)) {
      const r = relationshipsOf(dto, c.id);
      return { text: `${c.id}: ${r.outgoing.length ? `it can ${r.outgoing.map((x) => `${x.id} → ${list(x.to, 4)}`).join("; ")}` : "it starts no relationships"}${r.incoming.length ? `. It can be the target of ${r.incoming.map((x) => `${x.id} (from ${list(x.from, 4)})`).join("; ")}` : ""}.`, concepts: [c.id], relationships: [...r.outgoing, ...r.incoming].map((x) => x.id).slice(0, 8) };
    }
    const n = used.concepts[c.id];
    const where = graph ? ` In this configuration's graph there ${n === 1 ? "is" : "are"} ${n ?? 0}.` : "";
    const words2 = glossaryWordsFor(dto, c.id);
    return { text: `${c.id}${words2.length ? ` (also called ${words2.join(", ")})` : ""}: ${c.description || "no description"}. Domain ${c.domain ?? "none"}, defined by ${c.pack_id === "core" ? "the core" : c.pack_id}${c.parent ? `, a subclass of ${c.parent}` : ""}; ${plural(c.attributes.length, "attribute")}.${where}${c.role_only ? " Recorded by role only, never names or contact details." : ""}`, concepts: [c.id, ...(c.parent ? [c.parent] : [])], relationships: [] };
  }
  if (/ontolog/.test(q)) {
    return none(`The ontology is the rulebook behind this graph: core ${dto.ontology_version} with ${plural(dto.concepts.length, "concept")}, ${plural(dto.relationships.length, "relationship type")}, ${plural(dto.policies.length, "policy", "policies")} and ${plural(dto.templates.length, "query template")}, in ${dto.domains.length} domains. It holds no tenant data. Ask what a concept is, how two concepts relate, a concept's attributes, or the packs and policies.`);
  }
  return none("I can answer questions about the ontology: what a concept is, what can relate to what (for example \"What can own a Service?\"), a concept's attributes and allowed values, the packs, policies and query templates.");
}
