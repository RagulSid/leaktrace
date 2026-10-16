"""Load a topology pack (JSON) into a tenant graph. Used by the asset import and the seed CLI.

Pack format:
  {"pack": str, "source": "synthetic",
   "nodes": [{"id", "labels": [...], "props": {...}}],
   "flows": [{"id", "from", "to", "cap", "valve_id"?, "two_way"?, "normally_closed"?}],
   "links": [{"type", "from", "to", "props"?}]}

A two-way flow becomes two FLOWS_TO edges: `<id>` (dir 'normal') and `<id>_r` (dir 'reverse').
A normally closed flow (for example a backup link behind a closed valve) has cap_base 0 and open_cap = cap.
"""

import json
from collections import defaultdict
from pathlib import Path

from app.graph import queries
from app.graph.client import TenantGraph
from app.graph.schema import check_label, check_rel


def load_pack(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def flow_rows(flows: list[dict]) -> list[dict]:
    out = []
    for f in flows:
        cap = f["cap"]
        common = {"cap_base": 0 if f.get("normally_closed") else cap, "open_cap": cap, "valve_id": f.get("valve_id")}
        out.append({"id": f["id"], "from": f["from"], "to": f["to"], "dir": "normal", **common})
        if f.get("two_way"):
            out.append({"id": f["id"] + "_r", "from": f["to"], "to": f["from"], "dir": "reverse", **common})
    return out


def import_pack(tg: TenantGraph, pack: dict) -> dict:
    source = pack.get("source", "synthetic")
    counts = {"nodes": 0, "flows": 0, "links": 0}

    by_labels: dict[tuple, list] = defaultdict(list)
    for n in pack["nodes"]:
        labels = tuple(check_label(lb) for lb in n["labels"])
        by_labels[labels].append({"id": n["id"], "props": n.get("props", {})})
    node_tpl = queries.load("import_nodes")
    for labels, batch in by_labels.items():
        res = tg.write_text("import_nodes", node_tpl.replace("{labels}", ":".join(labels)), {"rows": batch, "source": source})
        counts["nodes"] += res.result_set[0][0]

    res = tg.write("import_flows", {"rows": flow_rows(pack.get("flows", [])), "source": source})
    counts["flows"] = res.result_set[0][0]

    by_rel: dict[str, list] = defaultdict(list)
    for ln in pack.get("links", []):
        by_rel[check_rel(ln["type"])].append({"from": ln["from"], "to": ln["to"], "props": ln.get("props", {})})
    link_tpl = queries.load("import_links")
    for rel, batch in by_rel.items():
        res = tg.write_text("import_links", link_tpl.replace("{rel}", rel), {"rows": batch, "source": source})
        counts["links"] += res.result_set[0][0]
    return counts
