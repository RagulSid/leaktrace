"""Wrappers around FalkorDB graph algorithms used as agent tools."""

from dataclasses import dataclass

from app.graph.client import TenantGraph, rows


class UnknownNodes(LookupError):
    pass


@dataclass
class FlowResult:
    max_flow: float
    edge_flows: dict[str, float]  # edge id -> flow, only edges carrying positive flow


def max_flow(tg: TenantGraph, sources: list[str], targets: list[str], cap_property: str = "cap_base") -> FlowResult:
    """algo.maxFlow over FLOWS_TO. For per-consumer feasibility call it once per critical consumer:
    with several targets the total says nothing about how flow is shared among them."""
    src, tgt = sorted(set(sources)), sorted(set(targets))
    if not src or not tgt:
        raise ValueError("max_flow needs at least one source and one target")
    if set(src) & set(tgt):
        raise ValueError("source and target sets must be disjoint")
    out = rows(tg.read("max_flow", {"sources": src, "targets": tgt, "cap": cap_property}))
    if not out or out[0]["n_sources"] != len(src) or out[0]["n_targets"] != len(tgt):
        raise UnknownNodes(f"some of {src} / {tgt} are not in graph {tg.name}")
    r = out[0]
    return FlowResult(float(r["maxFlow"]), dict(zip(r["edge_ids"], r["edge_flows"])))


def bfs_reach(tg: TenantGraph, start: str, depth: int = 10) -> list[str]:
    """Nodes reachable from `start` over FLOWS_TO in any modelled direction (start node excluded)."""
    out = tg.read("bfs_reach", {"start": start, "depth": int(depth)}).result_set
    if not out:
        raise UnknownNodes(start)
    return out[0][0]
