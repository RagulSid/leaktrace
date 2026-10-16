import cytoscape from "cytoscape";
import { useEffect, useRef } from "react";

export type MapData = {
  nodes: { id: string; kind: string; name: string | null; state: string | null; criticality: number | null }[];
  edges: { id: string; source: string; target: string; cap_base: number }[];
  sensors: { id: string; kind: string; state: string; watches: string }[];
  highlight: { path: string[]; suspect: string | null; affected: string[]; plan_valves: string[] };
};

const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** Left-to-right layers: each node one column after its furthest upstream neighbour. */
function layout(data: MapData): Record<string, { x: number; y: number }> {
  const preds: Record<string, string[]> = {};
  data.edges.forEach((e) => { (preds[e.target] ||= []).push(e.source); });
  const depth: Record<string, number> = {};
  const visit = (id: string, seen: Set<string>): number => {
    if (id in depth) return depth[id];
    if (seen.has(id)) return 0;
    seen.add(id);
    const d = Math.max(0, ...(preds[id] || []).map((p) => visit(p, seen) + 1));
    depth[id] = d;
    return d;
  };
  data.nodes.forEach((n) => visit(n.id, new Set()));
  const cols: Record<number, string[]> = {};
  data.nodes.forEach((n) => { (cols[depth[n.id]] ||= []).push(n.id); });
  const pos: Record<string, { x: number; y: number }> = {};
  Object.entries(cols).forEach(([d, ids]) => {
    ids.sort();
    ids.forEach((id, i) => { pos[id] = { x: Number(d) * 84, y: (i - (ids.length - 1) / 2) * 64 }; });
  });
  return pos;
}

export function MapView({ data, label }: { data: MapData; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const h = data.highlight;
    const alarms = new Set(data.sensors.filter((s) => s.state !== "OK").map((s) => s.watches));
    const pos = layout(data);
    const cy = cytoscape({
      container: ref.current,
      elements: [
        ...data.nodes.map((n) => ({
          // Only what the decision rests on carries a label, so the labels stay readable.
          data: { id: n.id, kind: n.kind, label: (h.path.includes(n.id) || h.suspect === n.id || h.affected.includes(n.id)
            || h.plan_valves.includes(n.id) || n.kind === "Consumer" || n.kind === "Source") ? (n.name || n.id) : "" },
          position: pos[n.id],
          classes: [
            h.path.includes(n.id) ? "path" : "", h.suspect === n.id ? "suspect" : "",
            h.affected.includes(n.id) ? "affected" : "", h.plan_valves.includes(n.id) ? "plan" : "",
            n.state === "closed" ? "closed" : "", alarms.has(n.id) ? "alarm" : "", (n.criticality || 0) >= 4 ? "key" : "",
          ].join(" "),
        })),
        ...data.edges.map((e) => ({
          data: { id: e.id, source: e.source, target: e.target },
          classes: [h.path.includes(e.source) && h.path.includes(e.target) ? "path" : "", e.cap_base === 0 ? "shut" : ""].join(" "),
        })),
      ],
      layout: { name: "preset", fit: true, padding: 24 },
      userZoomingEnabled: false,
      userPanningEnabled: false,
      boxSelectionEnabled: false,
      autoungrabify: true,
      style: [
        { selector: "node", style: { "background-color": token("--map-node"), "border-width": 1, "border-color": token("--control"),
          label: "data(label)", "font-size": 11, color: token("--text"), "text-wrap": "wrap", "text-max-width": "78px",
          "text-valign": "bottom", "text-margin-y": 4, width: 16, height: 16, "font-family": token("--font") } },
        { selector: "node[kind = 'Valve']", style: { shape: "diamond", width: 14, height: 14 } },
        { selector: "node[kind = 'Consumer']", style: { shape: "round-rectangle", width: 22, height: 16 } },
        { selector: "node[kind = 'Source']", style: { shape: "round-rectangle", width: 22, height: 22, "border-color": token("--ink") } },
        { selector: "node.key", style: { "border-width": 2, "border-color": token("--ink") } },
        { selector: "node.closed", style: { "background-color": token("--selected") } },
        { selector: "node.affected", style: { "border-style": "dashed", "border-width": 2, "border-color": token("--ok-needed") } },
        { selector: "node.path", style: { "border-color": token("--path"), "border-width": 3, color: token("--path-text") } },
        { selector: "node.suspect", style: { "border-color": token("--bad"), "border-width": 3, color: token("--bad") } },
        { selector: "node.plan", style: { "border-color": token("--ink"), "border-width": 4 } },
        { selector: "edge", style: { width: 1, "line-color": token("--map-line"), "curve-style": "bezier",
          "target-arrow-shape": "triangle", "target-arrow-color": token("--map-line"), "arrow-scale": 0.6 } },
        { selector: "edge.shut", style: { "line-style": "dashed" } },
        { selector: "edge.path", style: { width: 3, "line-color": token("--path"), "target-arrow-color": token("--path") } },
      ],
    });
    const onResize = () => cy.fit(undefined, 24);
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); cy.destroy(); };
  }, [data]);
  return <div className="map" ref={ref} role="img" aria-label={label} />;
}
