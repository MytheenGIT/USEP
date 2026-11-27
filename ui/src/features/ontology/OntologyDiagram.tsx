import cytoscape, { Core } from "cytoscape";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { GraphifyGraph } from "../../shared/api/types";
import { conceptColor } from "../graph/colors";
import { typeGraphElements } from "./ontologyModel";

export interface DiagramHandle { fit: () => void; }
const cssVar = (name: string, fallback: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
// Every concept can relate to many others, so a force layout is a knot. A circle keeps each concept readable; edge names show for the
// hovered or selected concept only.
const LAYOUT = { name: "circle", animate: false, padding: 50, avoidOverlap: true } as const;

/** The type diagram: concepts and the relationship types allowed between them, drawn from the ontology's Graphify graph. */
export const OntologyDiagram = forwardRef<DiagramHandle, { graph: GraphifyGraph; selected: string | null; onSelect: (concept: string) => void; themeKey: string }>(
  function OntologyDiagram({ graph, selected, onSelect, themeKey }, handle) {
    const box = useRef<HTMLDivElement>(null);
    const cy = useRef<Core | null>(null);
    const onSelectRef = useRef(onSelect);
    onSelectRef.current = onSelect;
    useImperativeHandle(handle, () => ({ fit: () => cy.current?.fit(undefined, 30) }));

    useEffect(() => {
      if (!box.current) return;
      const text = cssVar("--text", "#1b1f24");
      const edge = cssVar("--border-strong", "#8b949e");
      const canvas = cssVar("--canvas", "#ffffff");
      const instance = cytoscape({
        container: box.current,
        elements: typeGraphElements(graph).map((e) => ("source" in e.data ? e : { data: { ...e.data, color: conceptColor(e.data.id) } })),
        layout: LAYOUT,
        style: [
          { selector: "node", style: { "background-color": "data(color)", label: "data(label)", color: text, "font-size": 11, "text-valign": "bottom", "text-margin-y": 4, width: 24, height: 24 } },
          { selector: "node:selected", style: { "border-width": 3, "border-color": "#2563eb", "border-style": "solid" } },
          { selector: "edge", style: { width: 1, opacity: 0.45, "line-color": edge, "target-arrow-color": edge, "target-arrow-shape": "triangle", "curve-style": "bezier", "font-size": 9, color: text, "text-background-color": canvas, "text-background-opacity": 0.9, "text-background-padding": "2px" } },
          { selector: "edge[isa = 1]", style: { "line-style": "dashed", "line-color": "#d97706", "target-arrow-color": "#d97706", "target-arrow-shape": "triangle-tee", opacity: 0.8 } },
          { selector: "edge.hl", style: { label: "data(label)", width: 2, opacity: 1, "z-index": 10 } },
        ],
      });
      instance.on("tap", "node", (ev) => onSelectRef.current(ev.target.id()));
      instance.on("mouseover", "node", (ev) => ev.target.connectedEdges().addClass("hl"));
      instance.on("mouseout", "node", (ev) => { if (!ev.target.selected()) ev.target.connectedEdges().removeClass("hl"); });
      cy.current = instance;
      return () => { instance.destroy(); cy.current = null; };
    }, [graph, themeKey]);

    useEffect(() => {
      cy.current?.elements().unselect().removeClass("hl");
      if (selected) {
        const n = cy.current?.getElementById(selected);
        n?.select();
        n?.connectedEdges().addClass("hl");
      }
    }, [selected, graph, themeKey]);

    return <div ref={box} className="canvas" role="img" aria-label={`Diagram of ${graph.nodes.length} concepts and ${graph.links.length} relationships; the table below has the same information`} />;
  });
