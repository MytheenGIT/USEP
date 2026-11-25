import cytoscape, { Core } from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { Configuration, GraphDto } from "../api/types";
import { conceptColor } from "../graph";

export function GraphView({ token, config }: { token: string; config: Configuration }) {
  const [graph, setGraph] = useState<GraphDto | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<"graph" | "table">("graph");
  const box = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);

  useEffect(() => {
    let live = true;
    setGraph(null); setError(""); setSelected(null);
    api.getGraph(token, config.id).then((g) => live && setGraph(g)).catch((e) => live && setError(e instanceof Error ? e.message : "Could not load graph"));
    return () => { live = false; };
  }, [token, config.id]);

  const concepts = useMemo(() => [...new Set(graph?.nodes.map((n) => n.concept) ?? [])].sort(), [graph]);
  const visible = useMemo(() => {
    if (!graph) return { nodes: [], edges: [] };
    const q = search.trim().toLowerCase();
    const nodes = graph.nodes.filter((n) => !hidden.has(n.concept) && (!q || n.name.toLowerCase().includes(q) || n.concept.toLowerCase().includes(q)));
    const ids = new Set(nodes.map((n) => n.id));
    return { nodes, edges: graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target)) };
  }, [graph, hidden, search]);

  useEffect(() => {
    if (tab !== "graph" || !box.current) return;
    const styles = getComputedStyle(document.documentElement);
    const text = styles.getPropertyValue("--text").trim() || "#1b1f24";
    cy.current = cytoscape({
      container: box.current,
      elements: [
        ...visible.nodes.map((n) => ({ data: { id: n.id, label: n.name, concept: n.concept, color: conceptColor(n.concept), inferred: n.confidence !== undefined ? 1 : 0 } })),
        ...visible.edges.map((e) => ({ data: { id: e.id, source: e.source, target: e.target, label: e.relation, inferred: e.confidence < 1 ? 1 : 0 } })),
      ],
      layout: { name: "cose", animate: false, padding: 30 },
      style: [
        { selector: "node", style: { "background-color": "data(color)", label: "data(label)", color: text, "font-size": 11, "text-valign": "bottom", "text-margin-y": 4, width: 26, height: 26 } },
        { selector: "node[inferred = 1]", style: { "border-width": 2, "border-style": "dashed", "border-color": "#b45309" } },
        { selector: "node:selected", style: { "border-width": 3, "border-color": "#2563eb", "border-style": "solid" } },
        { selector: "edge", style: { width: 1.5, "line-color": "#8b949e", "target-arrow-color": "#8b949e", "target-arrow-shape": "triangle", "curve-style": "bezier", label: "data(label)", "font-size": 9, color: text, "text-background-color": "#fff", "text-background-opacity": 0.7 } },
        { selector: "edge[inferred = 1]", style: { "line-style": "dashed" } },
      ],
    });
    cy.current.on("tap", "node", (ev) => setSelected(ev.target.id()));
    cy.current.on("tap", (ev) => { if (ev.target === cy.current) setSelected(null); });
    return () => { cy.current?.destroy(); cy.current = null; };
  }, [visible, tab]);

  const node = graph?.nodes.find((n) => n.id === selected) ?? null;
  const edgesOf = graph?.edges.filter((e) => e.source === selected || e.target === selected) ?? [];
  const nameOf = (id: string) => graph?.nodes.find((n) => n.id === id)?.name ?? id;

  if (error) return <p role="alert" className="error">{error}</p>;
  if (!graph) return <p className="muted">Loading knowledge graph…</p>;

  return (
    <section aria-label="Knowledge graph">
      <div className="row">
        <h2>{config.name}</h2>
        <span className="muted small">Ontology {graph.ontology_version} · generated {new Date(graph.generated_at).toLocaleString()} · {graph.nodes.length} nodes, {graph.edges.length} edges</span>
      </div>
      <div className="toolbar">
        <input aria-label="Search nodes" placeholder="Search nodes" value={search} onChange={(e) => setSearch(e.target.value)} />
        <fieldset className="filters"><legend>Concepts</legend>
          {concepts.map((c) => (
            <label key={c} className="chip"><input type="checkbox" checked={!hidden.has(c)} onChange={() => setHidden((h) => { const s = new Set(h); if (s.has(c)) s.delete(c); else s.add(c); return s; })} />
              <span className="dot" style={{ background: conceptColor(c) }} />{c}</label>
          ))}
        </fieldset>
        <button onClick={() => cy.current?.fit(undefined, 30)} disabled={tab !== "graph"}>Fit</button>
        <button onClick={() => cy.current?.layout({ name: "cose", animate: false, padding: 30 }).run()} disabled={tab !== "graph"}>Reset layout</button>
        <div role="tablist" aria-label="Graph display">
          <button role="tab" aria-selected={tab === "graph"} className={tab === "graph" ? "tab active" : "tab"} onClick={() => setTab("graph")}>Graph</button>
          <button role="tab" aria-selected={tab === "table"} className={tab === "table" ? "tab active" : "tab"} onClick={() => setTab("table")}>Table</button>
        </div>
      </div>
      <p className="muted small">Knowledge-graph facts for this configuration. Dashed outline or line = inferred, lower confidence. These are stored facts, not ontology definitions.</p>
      <div className="split">
        {tab === "graph" ? <div ref={box} className="canvas" role="img" aria-label={`Graph of ${visible.nodes.length} nodes and ${visible.edges.length} relationships; use the Table tab for a text version`} /> : (
          <div className="tables">
            <table><caption>Nodes</caption><thead><tr><th>Name</th><th>Concept</th><th>Labels</th><th>Source</th><th>Confidence</th><th /></tr></thead>
              <tbody>{visible.nodes.map((n) => <tr key={n.id} className={n.id === selected ? "sel" : ""}><td>{n.name}</td><td>{n.concept}</td><td>{n.labels.join(", ")}</td><td>{n.source_system}</td><td>{n.confidence ?? "—"}</td><td><button onClick={() => setSelected(n.id)}>Details</button></td></tr>)}</tbody></table>
            <table><caption>Relationships</caption><thead><tr><th>From</th><th>Relationship</th><th>To</th><th>Confidence</th><th>Evidence</th></tr></thead>
              <tbody>{visible.edges.map((e) => <tr key={e.id}><td>{nameOf(e.source)}</td><td>{e.relation}</td><td>{nameOf(e.target)}</td><td>{e.confidence}</td><td>{e.evidence_ref}</td></tr>)}</tbody></table>
          </div>
        )}
        <aside aria-label="Details" className="details">
          {!node ? <p className="muted">Select a node to see its details.</p> : (
            <>
              <h3>{node.name}</h3>
              <p><span className="dot" style={{ background: conceptColor(node.concept) }} /> {node.concept} {node.labels.map((l) => <span key={l} className="badge">{l}</span>)}</p>
              <dl>
                <dt>Source</dt><dd>{node.source_system ?? "—"} {node.source_id ?? ""}</dd>
                <dt>Ontology version</dt><dd>{node.ontology_version ?? "—"}</dd>
                {node.confidence !== undefined && <><dt>Confidence (inferred)</dt><dd>{node.confidence}</dd></>}
                {Object.entries(node.properties).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{Array.isArray(v) ? v.join(", ") : String(v)}</dd></div>)}
              </dl>
              <h4>Relationships</h4>
              <ul>{edgesOf.map((e) => <li key={e.id}>{e.source === node.id ? <>{e.relation} → {nameOf(e.target)}</> : <>{nameOf(e.source)} {e.relation} →</>} <span className="muted">({e.confidence})</span></li>)}</ul>
            </>
          )}
        </aside>
      </div>
    </section>
  );
}
