import cytoscape, { Core } from "cytoscape";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { conceptColor } from "./colors";
import { VisibleGraph } from "./graphModel";

export interface GraphCanvasHandle {
  fit: () => void;
  relayout: () => void;
}

interface Props {
  graph: VisibleGraph;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /** Changes when the theme changes, so label colours are re-read from CSS. */
  themeKey: string;
}

// Spread the nodes out: the demo graphs have 20 to 30 nodes and the default pulls them into a knot with overlapping labels.
const LAYOUT = { name: "cose", animate: false, padding: 40, nodeRepulsion: () => 11000, idealEdgeLength: () => 95, nodeOverlap: 30, gravity: 0.45, numIter: 1500 } as const;
const cssVar = (name: string, fallback: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

export const GraphCanvas = forwardRef<GraphCanvasHandle, Props>(function GraphCanvas({ graph, selectedId, onSelect, themeKey }, handle) {
  const box = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useImperativeHandle(handle, () => ({
    fit: () => cy.current?.fit(undefined, 30),
    relayout: () => void cy.current?.layout(LAYOUT).run(),
  }));

  useEffect(() => {
    if (!box.current) return;
    const text = cssVar("--text", "#1b1f24");
    const edge = cssVar("--border-strong", "#8b949e");
    const canvas = cssVar("--canvas", "#ffffff");
    const instance = cytoscape({
      container: box.current,
      elements: [
        ...graph.nodes.map((n) => ({ data: { id: n.id, label: n.name, color: conceptColor(n.concept), inferred: n.confidence != null ? 1 : 0 } })),
        ...graph.edges.map((e) => ({ data: { id: e.id, source: e.source, target: e.target, label: e.relation, inferred: e.confidence < 1 ? 1 : 0 } })),
      ],
      layout: LAYOUT,
      style: [
        { selector: "node", style: { "background-color": "data(color)", label: "data(label)", color: text, "font-size": 11, "text-valign": "bottom", "text-margin-y": 4, width: 26, height: 26, "text-wrap": "ellipsis", "text-max-width": "140px" } },
        { selector: "node[inferred = 1]", style: { "border-width": 2, "border-style": "dashed", "border-color": "#d97706" } },
        { selector: "node:selected", style: { "border-width": 3, "border-color": "#2563eb", "border-style": "solid" } },
        { selector: "edge", style: { width: 1.5, "line-color": edge, "target-arrow-color": edge, "target-arrow-shape": "triangle", "curve-style": "bezier", label: "data(label)", "font-size": 9, color: text, "text-background-color": canvas, "text-background-opacity": 0.8 } },
        { selector: "edge[inferred = 1]", style: { "line-style": "dashed" } },
      ],
    });
    instance.on("tap", "node", (ev) => onSelectRef.current(ev.target.id()));
    instance.on("tap", (ev) => {
      if (ev.target === instance) onSelectRef.current(null);
    });
    cy.current = instance;
    return () => {
      instance.destroy();
      cy.current = null;
    };
  }, [graph, themeKey]);

  // Selection from the table or details panel is mirrored onto the canvas without rebuilding it.
  useEffect(() => {
    cy.current?.elements().unselect();
    if (selectedId) cy.current?.getElementById(selectedId).select();
  }, [selectedId, graph, themeKey]);

  return (
    <div
      ref={box}
      className="canvas"
      role="img"
      aria-label={`Graph of ${graph.nodes.length} nodes and ${graph.edges.length} relationships; use the Table view for a text version`}
    />
  );
});
