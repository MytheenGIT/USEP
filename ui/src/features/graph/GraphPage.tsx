import { useMemo, useRef, useState } from "react";
import { Link, paths } from "../../app/router";
import { api } from "../../shared/api/client";
import { useAsync } from "../../shared/hooks/useAsync";
import { formatDateTime } from "../../shared/lib/format";
import { Button, Card, EmptyState, ErrorMessage, Icon, Spinner } from "../../shared/ui";
import { useSession } from "../auth/AuthContext";
import { useConfiguration } from "../configurations/hooks";
import { conceptColor } from "./colors";
import { GraphCanvas, GraphCanvasHandle } from "./GraphCanvas";
import { conceptsOf, filterGraph, toggle } from "./graphModel";
import { NodeDetails } from "./NodeDetails";
import { NodeTables } from "./NodeTables";

export function GraphPage({ id, themeKey }: { id: string; themeKey: string }) {
  const { session, guard } = useSession();
  const { config } = useConfiguration(id);
  const { data: graph, error, loading, reload } = useAsync(() => guard(api.getGraph(session.token, id)), [id, session.token]);
  const [search, setSearch] = useState("");
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<"graph" | "table">("graph");
  const canvas = useRef<GraphCanvasHandle>(null);

  const visible = useMemo(() => (graph ? filterGraph(graph, { search, hiddenConcepts: hidden }) : { nodes: [], edges: [] }), [graph, search, hidden]);
  const node = graph?.nodes.find((n) => n.id === selectedId) ?? null;
  const crumbs = (
    <nav aria-label="Breadcrumb" className="crumbs">
      <Link to={paths.configurations()}>Configurations</Link> / <Link to={paths.configuration(id)}>{config?.name ?? "Configuration"}</Link> / <span>Knowledge graph</span>
    </nav>
  );

  if (loading && !graph) return <>{crumbs}<Spinner label="Loading knowledge graph" /></>;
  if (error || !graph) return <>{crumbs}<ErrorMessage onRetry={reload}>{error?.message ?? "Could not load the graph"}</ErrorMessage></>;

  return (
    <>
      {crumbs}
      <div className="page-head">
        <div>
          <h1>{config?.name ?? "Knowledge graph"}</h1>
          <p className="muted">Ontology {graph.ontology_version} · generated {formatDateTime(graph.generated_at)} · {graph.nodes.length} nodes, {graph.edges.length} relationships</p>
        </div>
        <div className="row-gap">
          <Link to={paths.ontology(id)} className="btn btn-secondary"><Icon name="book" size={16} /> Ontology</Link>
          <Link to={paths.agent(id)} className="btn btn-primary"><Icon name="chat" size={16} /> Ask the agent</Link>
        </div>
      </div>

      <Card>
        <div className="toolbar">
          <input aria-label="Search nodes" placeholder="Search nodes" value={search} onChange={(e) => setSearch(e.target.value)} />
          <fieldset className="filters">
            <legend className="sr-only">Concepts</legend>
            {conceptsOf(graph).map((c) => (
              <label key={c} className="chip">
                <input type="checkbox" checked={!hidden.has(c)} onChange={() => setHidden((h) => toggle(h, c))} />
                <span className="dot" style={{ background: conceptColor(c) }} aria-hidden="true" />{c}
              </label>
            ))}
          </fieldset>
          <span className="spacer" />
          <Button onClick={() => canvas.current?.fit()} disabled={view !== "graph"}>Fit</Button>
          <Button onClick={() => canvas.current?.relayout()} disabled={view !== "graph"}>Reset layout</Button>
          <div role="tablist" aria-label="Graph display" className="segmented">
            <button role="tab" aria-selected={view === "graph"} className={view === "graph" ? "seg active" : "seg"} onClick={() => setView("graph")}>Graph</button>
            <button role="tab" aria-selected={view === "table"} className={view === "table" ? "seg active" : "seg"} onClick={() => setView("table")}>Table</button>
          </div>
        </div>
        <p className="muted small">Stored facts for this configuration, not ontology definitions. A dashed outline or line marks an inferred item with lower confidence.</p>

        {graph.nodes.length === 0 ? (
          <EmptyState title="No graph nodes yet">The sources were read, but nothing in them mapped to an ontology concept. Jira issues, GitLab and GitHub changes, ServiceNow incidents and changes, and Confluence ADR pages are mapped today.</EmptyState>
        ) : (
          <div className="split">
            {view === "graph"
              ? <GraphCanvas ref={canvas} graph={visible} selectedId={selectedId} onSelect={setSelectedId} themeKey={themeKey} />
              : <NodeTables graph={graph} visible={visible} selectedId={selectedId} onSelect={setSelectedId} />}
            <NodeDetails graph={graph} node={node} onSelect={setSelectedId} configId={id} />
          </div>
        )}
      </Card>
    </>
  );
}
