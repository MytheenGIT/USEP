import { Link, paths } from "../../app/router";
import { GraphDto, GraphNodeDto } from "../../shared/api/types";
import { Badge } from "../../shared/ui";
import { conceptColor } from "./colors";
import { edgesOf, nameOf } from "./graphModel";

const show = (v: unknown) => (Array.isArray(v) ? v.join(", ") : v == null ? "—" : String(v));

export function NodeDetails({ graph, node, onSelect, configId }: { graph: GraphDto; node: GraphNodeDto | null; onSelect: (id: string) => void; configId?: string }) {
  if (!node) return <aside className="details" aria-label="Details"><p className="muted">Select a node to see its details.</p></aside>;
  const edges = edgesOf(graph, node.id);
  return (
    <aside className="details" aria-label="Details">
      <h3>{node.name}</h3>
      <p className="row-gap">
        <span className="dot" style={{ background: conceptColor(node.concept) }} aria-hidden="true" /> {node.concept}
        {node.labels.map((l) => <Badge key={l}>{l}</Badge>)}
      </p>
      {configId && <p className="small"><Link to={paths.ontology(configId, node.concept)}>Concept: {node.concept} (open its definition)</Link></p>}
      <dl className="kv">
        <div><dt>Source</dt><dd>{node.source_system ?? "—"} {node.source_id ?? ""}</dd></div>
        <div><dt>Ontology version</dt><dd>{node.ontology_version ?? "—"}</dd></div>
        {node.confidence != null && <div><dt>Confidence (inferred)</dt><dd>{node.confidence}</dd></div>}
        {Object.entries(node.properties).map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd className="wrap">{show(v)}</dd></div>
        ))}
      </dl>
      <h4>Relationships</h4>
      {edges.length === 0 ? <p className="muted small">None.</p> : (
        <ul className="rel-list">
          {edges.map((e) => {
            const out = e.source === node.id;
            const other = out ? e.target : e.source;
            return (
              <li key={e.id}>
                {out ? <>{e.relation} → </> : <>← {e.relation} from </>}
                <button className="link" onClick={() => onSelect(other)}>{nameOf(graph, other)}</button>
                <span className="muted"> ({e.confidence})</span>
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
