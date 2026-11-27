import { useMemo, useRef, useState } from "react";
import { Link, paths } from "../../app/router";
import { api } from "../../shared/api/client";
import { useAsync } from "../../shared/hooks/useAsync";
import { Badge, Button, Card, EmptyState, ErrorMessage, Spinner } from "../../shared/ui";
import { useSession } from "../auth/AuthContext";
import { useConfigurationList } from "../configurations/ConfigurationsContext";
import { useConfiguration } from "../configurations/hooks";
import { conceptColor } from "../graph/colors";
import { DiagramHandle, OntologyDiagram } from "./OntologyDiagram";
import { allowedValues, conceptsByDomain, driftMessage, glossaryWordsFor, labelUsage, ontologyProblems, relationshipsOf, statusBanners, usageCounts } from "./ontologyModel";

type Sub = "overview" | "concepts" | "relationships" | "labels" | "vocabularies" | "policies";
const SUBS: [Sub, string][] = [["overview", "Overview"], ["concepts", "Concepts"], ["relationships", "Relationships"], ["labels", "Labels"], ["vocabularies", "Vocabularies"], ["policies", "Queries and policies"]];

function ConceptLink({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  return (
    <button className="chip chip-button" onClick={() => onOpen(id)} aria-label={`Open concept ${id}`}>
      <span className="dot" style={{ background: conceptColor(id) }} aria-hidden="true" />{id}
    </button>
  );
}

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

  return (
    <>
      {crumbs}
      <div className="page-head">
        <div>
          <h1>Ontology</h1>
          <p className="muted">Core {dto.ontology_version} · {dto.concepts.length} concepts · {dto.relationships.length} relationship types · read only</p>
        </div>
        <Link to={paths.graph(id)} className="btn btn-secondary">Knowledge graph</Link>
      </div>
      {statusBanners(dto).map((b) => <div key={b} role="status" className="alert alert-warning">{b}</div>)}
      {driftMessage(config?.ontology, dto) && <div role="status" className="alert alert-warning">{driftMessage(config?.ontology, dto)}</div>}
      <Card>
        <p className="muted small">The rulebook, not the data: the kinds of thing and link that can exist. It holds no tenant data and cannot be edited here; changes go through Git, pack CI and review.</p>
        <div role="tablist" aria-label="Ontology views" className="segmented">
          {SUBS.map(([k, label]) => <button key={k} role="tab" aria-selected={sub === k} className={sub === k ? "seg active" : "seg"} onClick={() => setSub(k)}>{label}</button>)}
        </div>

        {sub === "overview" && (
          <div className="stack">
            <p>Digest <code title={dto.digest}>{dto.digest.slice(0, 12)}</code> <Button onClick={() => void copyDigest()}>{copied ? "Copied" : "Copy"}</Button> <span className="muted small">changes whenever any definition changes</span></p>
            <table>
              <caption>Packs</caption>
              <thead><tr><th>Id</th><th>Level</th><th>Version</th><th>Status</th><th>Signed</th><th>Content</th></tr></thead>
              <tbody>{dto.packs.map((p) => (
                <tr key={p.id}><td>{p.id}</td><td>{p.level}</td><td>{p.version}</td><td>{p.status}</td>
                  <td>{p.signed ? <Badge tone="success">signed</Badge> : <Badge tone="warning">unsigned</Badge>}</td>
                  <td>{p.reference_only ? <Badge tone="warning">placeholder</Badge> : "—"}</td></tr>
              ))}</tbody>
            </table>
            <p className="muted small">Domains: {dto.domains.join(", ")}</p>
            <h3>In this configuration</h3>
            {!config?.ontology ? <p className="muted">No graph has been built for this configuration yet, so nothing was checked against the ontology.</p> : (
              <dl className="kv">
                <div><dt>Graph checked against</dt><dd>Core {config.ontology.version} · digest <code title={config.ontology.digest}>{config.ontology.digest.slice(0, 12)}</code>{config.ontology.digest === dto.digest ? " (the current ontology)" : " (not the current ontology)"}</dd></div>
                <div><dt>Packs</dt><dd>{config.ontology.packs.join(", ")}</dd></div>
                <div><dt>Concepts in use</dt><dd>{Object.keys(used.concepts).length} of {dto.concepts.length} ({Object.values(used.concepts).reduce((a, b) => a + b, 0)} nodes)</dd></div>
                <div><dt>Relationship types in use</dt><dd>{Object.keys(used.relations).length} of {dto.relationships.length} ({Object.values(used.relations).reduce((a, b) => a + b, 0)} relationships)</dd></div>
                <div><dt>Left out by the ontology</dt><dd>{config.ontology.nodes_dropped} item(s), {config.ontology.edges_dropped} relationship(s){config.ontology.nodes_dropped + config.ontology.edges_dropped > 0 ? " — proposed from the sources but not allowed" : ""}</dd></div>
              </dl>
            )}
          </div>
        )}

        {sub === "concepts" && (
          <div className="split">
            <div className="tables">
              <input aria-label="Search concepts" placeholder="Search concepts or organisation words" value={search} onChange={(e) => setSearch(e.target.value)} />
              {groups.length === 0 && <p className="muted">No concept matches.</p>}
              {groups.map((g) => (
                <section key={g.domain}>
                  <h3>{g.domain}</h3>
                  <p>{g.concepts.map((c) => (
                    <button key={c.id} className={c.id === selected ? "chip chip-button selected" : "chip chip-button"} aria-pressed={c.id === selected} onClick={() => setSelected(c.id)}>
                      <span className="dot" style={{ background: conceptColor(c.id) }} aria-hidden="true" />{c.id}{c.level !== "core" && <Badge>{c.level}</Badge>}{used.concepts[c.id] ? <Badge tone="info" title="Nodes of this concept in this configuration's graph">{used.concepts[c.id]} in graph</Badge> : null}
                    </button>
                  ))}</p>
                </section>
              ))}
            </div>
            <aside className="details" aria-label="Concept details">
              {!concept ? <p className="muted">Select a concept to see its definition.</p> : (
                <>
                  <h3><span className="dot" style={{ background: conceptColor(concept.id) }} aria-hidden="true" /> {concept.id} {glossaryWordsFor(dto, concept.id).map((w) => <Badge key={w}>{w} ({concept.id})</Badge>)}</h3>
                  <p>{concept.description || <span className="muted">No description.</span>}</p>
                  {labels.some((l) => l.concept === concept.id) && (
                    <p className="small">Labels on its nodes: {labels.filter((l) => l.concept === concept.id).map((l) => <Badge key={l.label} title="A label refines a concept; it never replaces it">{l.label} ×{l.count}</Badge>)}</p>
                  )}
                  <p className="small">{graph ? <>In this configuration: <strong>{used.concepts[concept.id] ?? 0}</strong> node(s)</> : <span className="muted">No graph for this configuration yet.</span>}</p>
                  <p className="small">Domain <strong>{concept.domain ?? "none"}</strong> · level <strong>{concept.level}</strong> · pack <strong>{concept.pack_id}</strong>
                    {concept.role_only && <> · <Badge tone="warning">role only</Badge> recorded by role, never names or contact details</>}</p>
                  {concept.parent && <p className="small">Subclass of <ConceptLink id={concept.parent} onOpen={open} /></p>}
                  <table>
                    <caption>Attributes (including inherited)</caption>
                    <thead><tr><th>Name</th><th>Type</th><th>Required</th><th>Multi</th><th>Allowed values</th><th>Defined in</th></tr></thead>
                    <tbody>{concept.attributes.map((a) => {
                      const vals = allowedValues(dto, a.values_ref);
                      return (
                        <tr key={a.name}><td>{a.name}</td><td>{a.type}</td><td>{a.required ? "yes" : "no"}</td><td>{a.multi ? "yes" : "no"}</td>
                          <td>{vals ? vals.join(", ") : a.values_ref ? `(${a.values_ref})` : "—"}</td>
                          <td>{a.defined_in === concept.id ? "this concept" : <ConceptLink id={a.defined_in} onOpen={open} />}</td></tr>
                      );
                    })}</tbody>
                  </table>
                  {rels && (
                    <>
                      <h4>Relationships</h4>
                      <ul className="rel-list">
                        {rels.outgoing.map((r) => <li key={`o${r.id}`}>{r.id} → {r.to.map((t) => <ConceptLink key={t} id={t} onOpen={open} />)}</li>)}
                        {rels.incoming.map((r) => <li key={`i${r.id}`}>{r.from.map((f) => <ConceptLink key={f} id={f} onOpen={open} />)} {r.id} →</li>)}
                      </ul>
                    </>
                  )}
                </>
              )}
            </aside>
          </div>
        )}

        {sub === "relationships" && (
          <div className="stack">
            <div className="toolbar">
              <span className="muted small">Concepts and the relationship types allowed between them, read from this ontology's Graphify graph. Dashed amber lines mean a pack concept is a subclass (<code>is_a</code>). Select a concept to open it.</span>
              <span className="spacer" />
              <Button onClick={() => diagram.current?.fit()}>Fit</Button>
              <Button onClick={download}>Download Graphify graph.json</Button>
            </div>
            <OntologyDiagram ref={diagram} graph={graphify} selected={selected} onSelect={open} themeKey={themeKey} />
            <table>
              <caption>Relationship types</caption>
              <thead><tr><th>Id</th><th>From</th><th>To</th><th>Level</th><th>Same type</th><th>In this graph</th></tr></thead>
              <tbody>{dto.relationships.map((r) => (
                <tr key={r.id}><td>{r.id}</td><td>{r.from.map((f) => <ConceptLink key={f} id={f} onOpen={open} />)}</td>
                  <td>{r.to.map((t) => <ConceptLink key={t} id={t} onOpen={open} />)}</td><td>{r.level}</td><td>{r.same_type ? "yes" : "no"}</td><td>{graph ? used.relations[r.id] ?? 0 : "—"}</td></tr>
              ))}</tbody>
            </table>
          </div>
        )}

        {sub === "labels" && (
          <div className="stack">
            <p className="muted small">A label refines a concept (a domain, an organisation's own word, the kind of source record); it never replaces the concept, so a node is always a Service, a Team and so on, whatever it is called. Labels here are read from this configuration's graph.</p>
            <h3>Organisation words</h3>
            {Object.keys(dto.glossary).length === 0 ? (
              <p className="muted">None defined yet. The organisation pack's glossary maps the organisation's own words to concepts (for example "Squad" to Team); the reference pack only has placeholders.</p>
            ) : (
              <table>
                <caption className="sr-only">Organisation words</caption>
                <thead><tr><th>Word</th><th>Concept</th></tr></thead>
                <tbody>{Object.entries(dto.glossary).map(([w, c]) => <tr key={w}><td>{w}</td><td><ConceptLink id={c} onOpen={open} /></td></tr>)}</tbody>
              </table>
            )}
            <h3>Labels in this configuration</h3>
            {!graph ? <p className="muted">No graph for this configuration yet.</p> : labels.length === 0 ? <p className="muted">No node in this graph carries a label.</p> : (
              <table>
                <caption className="sr-only">Labels in use</caption>
                <thead><tr><th>Concept</th><th>Label</th><th>Nodes</th></tr></thead>
                <tbody>{labels.map((l) => <tr key={`${l.concept}/${l.label}`}><td><ConceptLink id={l.concept} onOpen={open} /></td><td>{l.label}</td><td>{l.count}</td></tr>)}</tbody>
              </table>
            )}
            <p className="muted small">Custom labels that a tenant defines on top of a concept are not shown here yet: their definitions are not served by the API.</p>
          </div>
        )}

        {sub === "vocabularies" && (
          <div>{Object.entries(dto.vocabularies).map(([name, vals]) => (
            <section key={name}><h3>{name}</h3><p>{vals.map((v) => <Badge key={v}>{v}</Badge>)}</p></section>
          ))}</div>
        )}

        {sub === "policies" && (
          <div className="stack">
            <p className="muted small">Policies only tighten access (deny, require approval, restrict to owners). A pack can never grant access.</p>
            <table>
              <caption>Policies</caption>
              <thead><tr><th>Id</th><th>Effect</th><th>Level</th></tr></thead>
              <tbody>{dto.policies.map((p) => <tr key={p.id}><td>{p.id}</td><td>{p.effect.replace(/_/g, " ")} (tightens access)</td><td>{p.level}</td></tr>)}</tbody>
            </table>
            <table>
              <caption>Query templates</caption>
              <thead><tr><th>Name</th><th>From</th><th>Max depth</th><th>Fan-out cap</th></tr></thead>
              <tbody>{dto.templates.map((t) => <tr key={`${t.pack_id}/${t.name}`}><td>{t.name}</td><td>{t.pack_id}</td><td>{t.max_depth}</td><td>{t.fanout_cap}</td></tr>)}</tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
