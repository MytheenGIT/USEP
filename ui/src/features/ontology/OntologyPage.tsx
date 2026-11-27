import { useMemo, useRef, useState } from "react";
import { Link, paths } from "../../app/router";
import { api } from "../../shared/api/client";
import { useAsync } from "../../shared/hooks/useAsync";
import { plural } from "../../shared/lib/format";
import { Badge, Button, Card, EmptyState, ErrorMessage, Spinner } from "../../shared/ui";
import type { Tone } from "../../shared/ui";
import { useSession } from "../auth/AuthContext";
import { useConfigurationList } from "../configurations/ConfigurationsContext";
import { useConfiguration } from "../configurations/hooks";
import { conceptColor } from "../graph/colors";
import { DiagramHandle, OntologyDiagram } from "./OntologyDiagram";
import { allowedValues, conceptsByDomain, driftMessage, EFFECT_LABEL, glossaryWordsFor, groupLabels, labelUsage, ontologyProblems, relationshipsOf, statusBanners, usageCounts } from "./ontologyModel";

type Sub = "overview" | "concepts" | "relationships" | "labels" | "vocabularies" | "policies";
const SUBS: [Sub, string][] = [["overview", "Overview"], ["concepts", "Concepts"], ["relationships", "Relationships"], ["labels", "Labels"], ["vocabularies", "Vocabularies"], ["policies", "Queries and policies"]];

function ConceptLink({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  return (
    <button type="button" className="onto-chip" onClick={() => onOpen(id)} aria-label={`Open concept ${id}`}>
      <span className="dot" style={{ background: conceptColor(id) }} aria-hidden="true" />{id}
    </button>
  );
}

const EFFECT_TONE: Record<string, Tone> = { deny: "danger", require_approval: "warning", restrict_to_owners: "info" };

export function OntologyPage({ id, concept: initialConcept, themeKey }: { id?: string; concept?: string; themeKey: string }) {
  const { items } = useConfigurationList();
  const configId = id ?? items?.[0]?.id;
  if (items === null && !id) return <Spinner label="Loading" />;
  if (!configId) return <EmptyState title="No configuration yet" action={<Link to={paths.newConfiguration()} className="btn btn-primary">New connector</Link>}>The ontology is shown for a configuration. Create one first.</EmptyState>;
  return <OntologyBody key={configId} id={configId} initialConcept={initialConcept} themeKey={themeKey} />;
}

function OntologyBody({ id, initialConcept, themeKey }: { id: string; initialConcept?: string; themeKey: string }) {
  const { session, guard } = useSession();
  const { config } = useConfiguration(id);
  // What this configuration's graph uses. Not every configuration has a graph (still reading, or failed): then there are no counts.
  const { data: graph } = useAsync(() => api.getGraph(session.token, id).catch(() => null), [id, session.token, config?.status]);
  const used = useMemo(() => usageCounts(graph), [graph]);
  const labels = useMemo(() => labelUsage(graph), [graph]);
  const { data, error, loading, reload } = useAsync(
    async () => {
      const [dto, graphify] = await guard(Promise.all([api.getOntology(session.token, id), api.getOntologyGraphify(session.token, id)]));
      const problems = ontologyProblems(dto);
      if (problems.length) throw new Error(`The server sent an ontology this console cannot read (${problems.slice(0, 3).join("; ")})`);
      return { dto, graphify };
    },
    [id, session.token],
  );
  const [sub, setSub] = useState<Sub>(initialConcept ? "concepts" : "overview");
  const [selected, setSelected] = useState<string | null>(initialConcept ?? null);
  const [search, setSearch] = useState("");
  const [copied, setCopied] = useState(false);
  const diagram = useRef<DiagramHandle>(null);
  const groups = useMemo(() => (data ? conceptsByDomain(data.dto, search) : []), [data, search]);

  const crumbs = (
    <nav aria-label="Breadcrumb" className="crumbs"><Link to={paths.configurations()}>Connectors</Link> / <Link to={paths.configuration(id)}>{config?.name ?? "Configuration"}</Link> / <span>Ontology</span></nav>
  );
  if (loading && !data) return <>{crumbs}<Spinner label="Loading the ontology" /></>;
  if (error || !data) return <>{crumbs}<ErrorMessage onRetry={reload}>{error?.message ?? "Could not load the ontology"}</ErrorMessage></>;

  const { dto, graphify } = data;
  const concept = dto.concepts.find((c) => c.id === selected) ?? null;
  const rels = concept ? relationshipsOf(dto, concept.id) : null;
  const open = (c: string) => { setSelected(c); setSub("concepts"); };
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(graphify, null, 1)], { type: "application/json" }));
    Object.assign(document.createElement("a"), { href: url, download: "graph.json" }).click();
    URL.revokeObjectURL(url);
  };
  const copyDigest = async () => {
    try { await navigator.clipboard.writeText(dto.digest); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard blocked: the full digest is on hover */ }
  };

  const notices = [...statusBanners(dto), ...(driftMessage(config?.ontology, dto) ? [driftMessage(config?.ontology, dto) as string] : [])];
  const labelGroups = groupLabels(labels);
  const totalNodes = Object.values(used.concepts).reduce((a, b) => a + b, 0);
  const totalRels = Object.values(used.relations).reduce((a, b) => a + b, 0);

  return (
    <div className="onto">
      {crumbs}
      <div className="page-head">
        <div>
          <h1>Ontology</h1>
          <p className="muted">Core {dto.ontology_version} · {dto.concepts.length} concepts · {dto.relationships.length} relationship types · read only</p>
        </div>
        <Link to={paths.graph(id)} className="btn btn-secondary">Knowledge graph</Link>
      </div>
      {notices.length > 0 && (
        <div role="status" className="alert alert-warning onto-notices"><ul>{notices.map((n) => <li key={n}>{n}</li>)}</ul></div>
      )}
      <Card>
        <p className="onto-intro">The rulebook, not the data: the kinds of thing and link that can exist. It holds no tenant data and cannot be edited here; changes go through Git, pack CI and review.</p>
        <div role="tablist" aria-label="Ontology views" className="onto-tabs">
          {SUBS.map(([k, label]) => <button key={k} type="button" role="tab" aria-selected={sub === k} className="onto-tab" onClick={() => setSub(k)}>{label}</button>)}
        </div>

        {sub === "overview" && (
          <div className="onto-section">
            <div className="onto-meta">
              <span className="muted small">Digest</span>
              <code title={dto.digest}>{dto.digest.slice(0, 12)}</code>
              <Button className="btn-sm" onClick={() => void copyDigest()}>{copied ? "Copied" : "Copy"}</Button>
              <span className="muted small">changes whenever any definition changes</span>
            </div>
            <h3 className="onto-h">Packs</h3>
            <div className="onto-tablewrap">
              <table>
                <caption className="sr-only">Packs</caption>
                <thead><tr><th>Id</th><th>Level</th><th>Version</th><th>Status</th><th>Signed</th><th>Content</th></tr></thead>
                <tbody>{dto.packs.map((p) => (
                  <tr key={p.id}><td className="mono">{p.id}</td><td>{p.level}</td><td>{p.version}</td><td>{p.status}</td>
                    <td>{p.signed ? <Badge tone="success">signed</Badge> : <Badge tone="warning">unsigned</Badge>}</td>
                    <td>{p.reference_only ? <Badge tone="warning">placeholder</Badge> : "—"}</td></tr>
                ))}</tbody>
              </table>
            </div>
            <h3 className="onto-h">Domains</h3>
            <div className="onto-chips">{dto.domains.map((d) => <Badge key={d}>{d}</Badge>)}</div>
            <h3 className="onto-h">In this configuration</h3>
            {!config?.ontology ? <p className="onto-empty">No graph has been built for this configuration yet, so nothing was checked against the ontology.</p> : (
              <dl className="onto-stats">
                <div className="onto-stat"><dt>Concepts in use</dt><dd>{Object.keys(used.concepts).length} of {dto.concepts.length} ({plural(totalNodes, "node")})</dd></div>
                <div className="onto-stat"><dt>Relationship types in use</dt><dd>{Object.keys(used.relations).length} of {dto.relationships.length} ({plural(totalRels, "relationship")})</dd></div>
                <div className="onto-stat"><dt>Left out by the ontology</dt><dd>{plural(config.ontology.nodes_dropped, "item")}, {plural(config.ontology.edges_dropped, "relationship")}{config.ontology.nodes_dropped + config.ontology.edges_dropped > 0 ? " (proposed from the sources, not allowed)" : ""}</dd></div>
                <div className="onto-stat"><dt>Graph checked against</dt><dd>Core {config.ontology.version} · <code title={config.ontology.digest}>{config.ontology.digest.slice(0, 12)}</code> {config.ontology.digest === dto.digest ? "(the current ontology)" : "(not the current ontology)"}</dd></div>
                <div className="onto-stat onto-stat-wide"><dt>Packs</dt><dd>{config.ontology.packs.join(", ")}</dd></div>
              </dl>
            )}
          </div>
        )}

        {sub === "concepts" && (
          <div className="onto-split">
            <div>
              <input className="onto-search" aria-label="Search concepts" placeholder="Search concepts or organisation words" value={search} onChange={(e) => setSearch(e.target.value)} />
              <div className="onto-list">
                {groups.length === 0 && <p className="onto-empty">No concept matches.</p>}
                {groups.map((g) => (
                  <section key={g.domain}>
                    <h3 className="onto-domain">{g.domain}</h3>
                    <div className="onto-chips">{g.concepts.map((c) => (
                      <button key={c.id} type="button" className="onto-chip" aria-pressed={c.id === selected} onClick={() => setSelected(c.id)}>
                        <span className="dot" style={{ background: conceptColor(c.id) }} aria-hidden="true" />{c.id}
                        {c.level !== "core" && <Badge>{c.level}</Badge>}
                        {used.concepts[c.id] ? <Badge tone="info" title="Nodes of this concept in this configuration's graph">{used.concepts[c.id]}</Badge> : null}
                      </button>
                    ))}</div>
                  </section>
                ))}
              </div>
            </div>
            <aside className="onto-detail" aria-label="Concept details">
              {!concept ? <p className="onto-empty">Select a concept to see its definition.</p> : (
                <>
                  <h3><span className="dot" style={{ background: conceptColor(concept.id) }} aria-hidden="true" />{concept.id}{glossaryWordsFor(dto, concept.id).map((w) => <Badge key={w}>{w}</Badge>)}</h3>
                  <p>{concept.description || <span className="muted">No description.</span>}</p>
                  <div className="onto-facts">
                    <span className="onto-fact">Domain <b>{concept.domain ?? "none"}</b></span>
                    <span className="onto-fact">Level <b>{concept.level}</b></span>
                    <span className="onto-fact">Pack <b>{concept.pack_id}</b></span>
                    {concept.parent && <span className="onto-fact">Subclass of <b>{concept.parent}</b></span>}
                    {graph && <span className="onto-fact">In this graph <b>{used.concepts[concept.id] ?? 0}</b></span>}
                    {concept.role_only && <Badge tone="warning" title="Recorded by role, never names or contact details">role only</Badge>}
                  </div>
                  {labels.some((l) => l.concept === concept.id) && (
                    <div>
                      <h4 className="onto-h">Labels on its nodes</h4>
                      <div className="onto-chips">{labels.filter((l) => l.concept === concept.id).map((l) => <Badge key={l.label} title="A label refines a concept; it never replaces it">{l.label} ×{l.count}</Badge>)}</div>
                    </div>
                  )}
                  {concept.parent && <div className="onto-chips"><span className="muted small">Subclass of</span><ConceptLink id={concept.parent} onOpen={open} /></div>}
                  <div>
                    <h4 className="onto-h">Attributes ({concept.attributes.length}, including inherited)</h4>
                    <ul className="onto-attrs">{concept.attributes.map((a) => {
                      const vals = allowedValues(dto, a.values_ref);
                      return (
                        <li key={a.name} className="onto-attr">
                          <div className="onto-attr-head">
                            <span className="onto-attr-name">{a.name}</span>
                            <Badge>{a.type}</Badge>
                            {a.required && <Badge tone="warning">required</Badge>}
                            {a.multi && <Badge>many</Badge>}
                          </div>
                          {vals && <div className="onto-chips">{vals.map((v) => <Badge key={v}>{v}</Badge>)}</div>}
                          {!vals && a.values_ref && <span className="onto-attr-from">Values: {a.values_ref}</span>}
                          {a.defined_in !== concept.id && <span className="onto-attr-from">Inherited from <ConceptLink id={a.defined_in} onOpen={open} /></span>}
                        </li>
                      );
                    })}</ul>
                  </div>
                  {rels && (rels.outgoing.length > 0 || rels.incoming.length > 0) && (
                    <div>
                      <h4 className="onto-h">Relationships</h4>
                      <ul className="onto-rels">
                        {rels.outgoing.map((r) => <li key={`o${r.id}`} className="onto-rel"><code>{r.id} →</code><div className="onto-chips">{r.to.map((t) => <ConceptLink key={t} id={t} onOpen={open} />)}</div></li>)}
                        {rels.incoming.map((r) => <li key={`i${r.id}`} className="onto-rel"><code>← {r.id}</code><div className="onto-chips">{r.from.map((f) => <ConceptLink key={f} id={f} onOpen={open} />)}</div></li>)}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </aside>
          </div>
        )}

        {sub === "relationships" && (
          <div className="onto-section">
            <div className="onto-bar">
              <p className="onto-note">Concepts and the relationship types allowed between them, read from this ontology's Graphify graph. Dashed amber lines mean a pack concept is a subclass (<code>is_a</code>). Select a concept to open it.</p>
              <div className="row-gap">
                <Button onClick={() => diagram.current?.fit()}>Fit</Button>
                <Button onClick={download}>Download Graphify graph.json</Button>
              </div>
            </div>
            <OntologyDiagram ref={diagram} graph={graphify} selected={selected} onSelect={open} themeKey={themeKey} />
            <h3 className="onto-h">Relationship types</h3>
            <div className="onto-tablewrap">
              <table>
                <caption className="sr-only">Relationship types</caption>
                <thead><tr><th>Id</th><th>From</th><th>To</th><th className="num">In graph</th></tr></thead>
                <tbody>{dto.relationships.map((r) => (
                  <tr key={r.id}>
                    <td><div className="onto-cell"><span className="onto-mono">{r.id}</span>{r.level !== "core" && <Badge title="The level that defined it">{r.level}</Badge>}{r.same_type && <Badge title="Both ends must be the same core concept">same type</Badge>}</div></td>
                    <td><div className="onto-cell">{r.from.map((f) => <ConceptLink key={f} id={f} onOpen={open} />)}</div></td>
                    <td><div className="onto-cell">{r.to.map((t) => <ConceptLink key={t} id={t} onOpen={open} />)}</div></td>
                    <td className="num">{graph ? used.relations[r.id] ?? 0 : "—"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </div>
        )}

        {sub === "labels" && (
          <div className="onto-section">
            <p className="onto-note">A label refines a concept (a domain, an organisation's own word, the kind of source record); it never replaces the concept, so a node is always a Service, a Team and so on, whatever it is called. Labels here are read from this configuration's graph.</p>
            <h3 className="onto-h">Organisation words</h3>
            {Object.keys(dto.glossary).length === 0 ? (
              <p className="onto-empty">None defined yet. The organisation pack's glossary maps the organisation's own words to concepts (for example "Squad" to Team); the reference pack only has placeholders.</p>
            ) : (
              <div className="onto-tablewrap">
                <table>
                  <caption className="sr-only">Organisation words</caption>
                  <thead><tr><th>Word</th><th>Concept</th></tr></thead>
                  <tbody>{Object.entries(dto.glossary).map(([w, c]) => <tr key={w}><td>{w}</td><td><div className="onto-cell"><ConceptLink id={c} onOpen={open} /></div></td></tr>)}</tbody>
                </table>
              </div>
            )}
            <h3 className="onto-h">Labels in this configuration</h3>
            {!graph ? <p className="onto-empty">No graph for this configuration yet.</p> : labelGroups.length === 0 ? <p className="onto-empty">No node in this graph carries a label.</p> : (
              <div className="onto-tablewrap">
                <table>
                  <caption className="sr-only">Labels in use</caption>
                  <thead><tr><th>Concept</th><th>Labels (nodes)</th><th className="num">Nodes</th></tr></thead>
                  <tbody>{labelGroups.map((g) => (
                    <tr key={g.concept}>
                      <td><div className="onto-cell"><ConceptLink id={g.concept} onOpen={open} /></div></td>
                      <td><div className="onto-cell">{g.labels.map((l) => <Badge key={l.label}>{l.label} ×{l.count}</Badge>)}</div></td>
                      <td className="num">{used.concepts[g.concept] ?? 0}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            <p className="onto-note">Custom labels that a tenant defines on top of a concept are not shown here yet: their definitions are not served by the API.</p>
          </div>
        )}

        {sub === "vocabularies" && (
          <div className="onto-vocab">{Object.entries(dto.vocabularies).map(([name, vals]) => (
            <section key={name} className="onto-vocab-card">
              <h3>{name}<span>{plural(vals.length, "value")}</span></h3>
              <div className="onto-chips">{vals.map((v) => <Badge key={v}>{v}</Badge>)}</div>
            </section>
          ))}</div>
        )}

        {sub === "policies" && (
          <div className="onto-section">
            <p className="onto-note">Every policy only tightens access (deny, require approval, restrict to owners). A pack can never grant access.</p>
            <h3 className="onto-h">Policies</h3>
            <div className="onto-tablewrap">
              <table>
                <caption className="sr-only">Policies</caption>
                <thead><tr><th>Id</th><th>Effect</th><th>Level</th></tr></thead>
                <tbody>{dto.policies.map((p) => <tr key={p.id}><td className="mono">{p.id}</td><td><Badge tone={EFFECT_TONE[p.effect] ?? "neutral"}>{EFFECT_LABEL[p.effect] ?? p.effect}</Badge></td><td>{p.level}</td></tr>)}</tbody>
              </table>
            </div>
            <h3 className="onto-h">Query templates</h3>
            <div className="onto-tablewrap">
              <table>
                <caption className="sr-only">Query templates</caption>
                <thead><tr><th>Name</th><th>From</th><th className="num">Max depth</th><th className="num">Fan-out cap</th></tr></thead>
                <tbody>{dto.templates.map((t) => <tr key={`${t.pack_id}/${t.name}`}><td className="mono">{t.name}</td><td>{t.pack_id}</td><td className="num">{t.max_depth}</td><td className="num">{t.fanout_cap}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
