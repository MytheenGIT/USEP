import { GraphDto } from "../../shared/api/types";
import { Button } from "../../shared/ui";
import { nameOf, VisibleGraph } from "./graphModel";

/** Text version of the graph, for screen readers and for exact reading. */
export function NodeTables({ graph, visible, selectedId, onSelect }: { graph: GraphDto; visible: VisibleGraph; selectedId: string | null; onSelect: (id: string) => void }) {
  return (
    <div className="tables">
      <table>
        <caption>Nodes</caption>
        <thead><tr><th>Name</th><th>Concept</th><th>Labels</th><th>Source</th><th>Confidence</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {visible.nodes.map((n) => (
            <tr key={n.id} className={n.id === selectedId ? "sel" : ""}>
              <td>{n.name}</td><td>{n.concept}</td><td>{n.labels.join(", ")}</td><td>{n.source_system ?? "—"}</td><td>{n.confidence ?? "—"}</td>
              <td><Button onClick={() => onSelect(n.id)}>Details</Button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <table>
        <caption>Relationships</caption>
        <thead><tr><th>From</th><th>Relationship</th><th>To</th><th>Confidence</th><th>Evidence</th></tr></thead>
        <tbody>
          {visible.edges.map((e) => (
            <tr key={e.id}><td>{nameOf(graph, e.source)}</td><td>{e.relation}</td><td>{nameOf(graph, e.target)}</td><td>{e.confidence}</td><td className="wrap">{e.evidence_ref ?? "—"}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
