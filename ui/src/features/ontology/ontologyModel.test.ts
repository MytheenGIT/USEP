import { describe, expect, it } from "vitest";
import { MOCK_PASSWORD, MOCK_USER, mockApi } from "../../shared/api/mock";
import { OntologyDto } from "../../shared/api/types";
import { allowedValues, conceptsByDomain, driftMessage, glossaryWordsFor, ontologyProblems, relationshipsOf, statusBanners, typeGraphElements, usageCounts, labelUsage, groupLabels } from "./ontologyModel";

async function load() {
  const s = await mockApi.login(MOCK_USER, MOCK_PASSWORD);
  const id = (await mockApi.listConfigurations(s.token))[0].id;      // the demo starts with finished configurations
  return { token: s.token, id, dto: await mockApi.getOntology(s.token, id), graphify: await mockApi.getOntologyGraphify(s.token, id) };
}

describe("ontology mock and contract", () => {
  it("returns a valid OntologyDto", async () => expect(ontologyProblems((await load()).dto)).toEqual([]));
  it("needs a session and a known configuration", async () => {
    const { token, id } = await load();
    await expect(mockApi.getOntology("bad", id)).rejects.toMatchObject({ status: 401 });
    await expect(mockApi.getOntology(token, "nope")).rejects.toMatchObject({ status: 404 });
    await expect(mockApi.getOntologyGraphify(token, "nope")).rejects.toMatchObject({ status: 404 });
  });
  it("rejects a malformed answer", () => {
    expect(ontologyProblems(null)).toEqual(["not an object"]);
    expect(ontologyProblems({ concepts: [{ id: "A", parent: "Missing", attributes: [] }] }).join()).toContain("unknown parent Missing");
  });
});

describe("status banners", () => {
  it("warns about placeholder and unsigned packs", async () => {
    const b = statusBanners((await load()).dto);
    expect(b.some((x) => x.startsWith("Placeholder content"))).toBe(true);
    expect(b.some((x) => x.startsWith("Unsigned"))).toBe(true);
  });
  it("is quiet when everything is real and signed", async () => {
    const { dto } = await load();
    const clean: OntologyDto = { ...dto, packs: dto.packs.map((p) => ({ ...p, reference_only: false, signed: true })) };
    expect(statusBanners(clean)).toEqual([]);
  });
});

describe("concepts", () => {
  it("shows where an inherited attribute is defined", async () => {
    const { dto } = await load();
    const inherited = dto.concepts.flatMap((c) => c.attributes.filter((a) => a.defined_in !== c.id));
    expect(inherited.length).toBeGreaterThan(0);
    for (const a of inherited) expect(dto.concepts.find((x) => x.id === a.defined_in)).toBeTruthy();
  });
  it("groups by domain and searches by id, description and organisation word", async () => {
    const { dto } = await load();
    expect(conceptsByDomain(dto, "").reduce((n, g) => n + g.concepts.length, 0)).toBe(dto.concepts.length);
    expect(conceptsByDomain(dto, "service").flatMap((g) => g.concepts).map((c) => c.id)).toContain("Service");
    const withWords: OntologyDto = { ...dto, glossary: { Squad: "Team" } };          // the reference glossary is empty
    expect(conceptsByDomain(withWords, "squad").flatMap((g) => g.concepts).map((c) => c.id)).toEqual(["Team"]);
    expect(glossaryWordsFor(withWords, "Team")).toEqual(["Squad"]);
    expect(conceptsByDomain(dto, "zzzz-no-such")).toEqual([]);
  });
  it("lists relationships and resolves allowed values", async () => {
    const { dto } = await load();
    expect(relationshipsOf(dto, "Team").outgoing.map((r) => r.id)).toContain("owns");
    expect(relationshipsOf(dto, "Service").incoming.map((r) => r.id)).toContain("owns");
    const ref = dto.concepts.flatMap((c) => c.attributes).find((a) => a.values_ref)?.values_ref ?? null;
    expect(allowedValues(dto, ref)?.length).toBeGreaterThan(0);
    expect(allowedValues(dto, null)).toBeNull();
  });
});

describe("Graphify graph", () => {
  it("is the same ontology: one node per concept, one link per allowed type pair, is_a for subclasses", async () => {
    const { dto, graphify } = await load();
    expect(graphify.nodes.map((n) => n.id).sort()).toEqual(dto.concepts.map((c) => c.id).sort());
    expect(graphify.graph.ontology_digest).toBe(dto.digest);
    expect(new Set(graphify.links.map((l) => l.relation).filter((r) => r !== "is_a"))).toEqual(new Set(dto.relationships.map((r) => r.id)));
    expect(graphify.links.filter((l) => l.relation === "is_a").length).toBe(dto.concepts.filter((c) => c.parent).length);
    expect(typeGraphElements(graphify).filter((e) => "source" in e.data).length).toBe(graphify.links.length);
  });
});

describe("a configuration and its ontology", () => {
  it("a ready demo configuration is pinned to the ontology the console shows", async () => {
    const { token, id, dto } = await load();
    const config = await mockApi.getConfiguration(token, id);
    expect(config.ontology?.digest).toBe(dto.digest);
    expect(config.ontology?.version).toBe(dto.ontology_version);
    expect(config.ontology?.packs[0]).toMatch(/^core@/);
    expect((await mockApi.getGraph(token, id)).ontology_digest).toBe(dto.digest);
  });
  it("counts what the configuration's graph uses, and every used concept and relationship exists in the ontology", async () => {
    const { token, id, dto } = await load();
    const u = usageCounts(await mockApi.getGraph(token, id));
    expect(Object.keys(u.concepts).length).toBeGreaterThan(0);
    for (const c of Object.keys(u.concepts)) expect(dto.concepts.map((x) => x.id)).toContain(c);
    for (const r of Object.keys(u.relations)) expect(dto.relationships.map((x) => x.id)).toContain(r);
    expect(usageCounts(null)).toEqual({ concepts: {}, relations: {} });
  });
  it("flags a change of ontology since the graph was built, and is quiet when they match", async () => {
    const { token, id, dto } = await load();
    const pin = (await mockApi.getConfiguration(token, id)).ontology!;
    expect(driftMessage(pin, dto)).toBeNull();
    expect(driftMessage(null, dto)).toBeNull();
    expect(driftMessage({ ...pin, digest: "f".repeat(64) }, dto)).toContain("changed since this configuration's graph was built");
  });
});

describe("the demo graph follows the ontology", () => {
  it("every node concept and relationship is defined, and each relationship joins concepts it allows (subclasses count as their parent)", async () => {
    const { token, dto } = await load();
    const parent = (c: string): string[] => { const k = dto.concepts.find((x) => x.id === c); return k ? [c, ...(k.parent ? parent(k.parent) : [])] : []; };
    const configs = await mockApi.listConfigurations(token);
    expect(configs.length).toBeGreaterThan(1);
    for (const c of configs) {
      const g = await mockApi.getGraph(token, c.id);
      const concept = new Map(g.nodes.map((n) => [n.id, n.concept]));
      for (const n of g.nodes) expect(dto.concepts.map((x) => x.id), `${c.name}: ${n.id}`).toContain(n.concept);
      for (const e of g.edges) {
        const rel = dto.relationships.find((r) => r.id === e.relation);
        expect(rel, `${c.name}: relationship ${e.relation}`).toBeTruthy();
        expect(parent(concept.get(e.source) ?? "").some((x) => rel!.from.includes(x)), `${c.name}: ${e.source} ${e.relation}`).toBe(true);
        expect(parent(concept.get(e.target) ?? "").some((x) => rel!.to.includes(x)), `${c.name}: ${e.relation} ${e.target}`).toBe(true);
      }
    }
  });
});

describe("labels", () => {
  const g = (labels: string[][]) => ({ configuration_id: "c", generated_at: "", ontology_version: "0.1.0",
    nodes: labels.map((l, i) => ({ id: `n${i}`, concept: i < 2 ? "Change" : "Team", name: `n${i}`, labels: l, properties: {} })), edges: [] });
  it("counts labels per concept, most used first, and never merges two concepts' labels", () => {
    expect(labelUsage(g([["merge_request"], ["merge_request", "pull_request"], ["Squad"]]))).toEqual([
      { concept: "Change", label: "merge_request", count: 2 }, { concept: "Change", label: "pull_request", count: 1 },
      { concept: "Team", label: "Squad", count: 1 },
    ]);
  });
  it("is empty without a graph or without labels", () => {
    expect(labelUsage(null)).toEqual([]);
    expect(labelUsage(g([[], []]))).toEqual([]);
  });
  it("every label in the demo graph sits on a concept the ontology defines", async () => {
    const { token, dto } = await load();
    const used = labelUsage(await mockApi.getGraph(token, (await mockApi.listConfigurations(token))[0].id));
    expect(used.length).toBeGreaterThan(0);
    for (const u of used) expect(dto.concepts.map((c) => c.id)).toContain(u.concept);
  });
});

describe("groupLabels", () => {
  it("makes one row per concept with its labels in order", () => {
    expect(groupLabels([
      { concept: "Change", label: "merge_request", count: 2 }, { concept: "Change", label: "pull_request", count: 1 },
      { concept: "Team", label: "Squad", count: 1 },
    ])).toEqual([
      { concept: "Change", labels: [{ label: "merge_request", count: 2 }, { label: "pull_request", count: 1 }] },
      { concept: "Team", labels: [{ label: "Squad", count: 1 }] },
    ]);
    expect(groupLabels([])).toEqual([]);
  });
});
