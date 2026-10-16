"""Option what-if through capacity variants (gate G1).

An option is evaluated by writing `cap_<optionId>` on every FLOWS_TO edge (closed valve -> 0,
opened valve -> open_cap, otherwise cap_base) and running algo.maxFlow with that capacity property.
algo.maxFlow fails if any FLOWS_TO edge lacks the property, so every edge gets one.
The property name travels only as a key inside a parameter map, never in query text, and is built
from a server-generated option id that must match ^[a-z0-9_]+$.
"""

import re
from contextlib import contextmanager

from app.graph.client import TenantGraph, rows

_OPTION_ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")


def variant_property(option_id: str) -> str:
    if not isinstance(option_id, str) or not _OPTION_ID_RE.fullmatch(option_id):
        raise ValueError(f"invalid option id: {option_id!r}")
    return f"cap_{option_id}"


def apply_variant(tg: TenantGraph, option_id: str, close_valves=(), open_valves=(), demand_caps: bool = False) -> str:
    """With demand_caps, links into a consumer are capped at its required_flow, so a max-flow to several
    consumers at once gives the total that can actually be delivered against their demands."""
    prop = variant_property(option_id)
    close, opened = set(close_valves), set(open_valves)
    if close & opened:
        raise ValueError(f"valves both closed and opened: {sorted(close & opened)}")
    edges = rows(tg.read("flow_edges_all"))
    unknown = (close | opened) - {e["valve_id"] for e in edges if e["valve_id"]}
    if unknown:
        raise ValueError(f"valves control no FLOWS_TO edge: {sorted(unknown)}")
    out = []
    for e in edges:
        v = e["valve_id"]
        cap = 0 if v in close else e["open_cap"] if v in opened else e["cap_base"]
        if demand_caps and e["demand"] is not None:
            cap = min(cap, e["demand"])
        out.append({"id": e["id"], "props": {prop: cap}})
    tg.write("flow_edges_set_props", {"rows": out})
    return prop


def clear_variant(tg: TenantGraph, option_id: str) -> None:
    tg.write("flow_edges_clear_props", {"nulls": {variant_property(option_id): None}})


@contextmanager
def variant(tg: TenantGraph, option_id: str, close_valves=(), open_valves=(), demand_caps: bool = False):
    prop = apply_variant(tg, option_id, close_valves, open_valves, demand_caps)
    try:
        yield prop
    finally:
        clear_variant(tg, option_id)
