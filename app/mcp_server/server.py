"""LeakTrace domain tool server (MCP).

The tenant graph is bound server-side from LEAKTRACE_TENANT when the process starts. No tool takes
a tenant or a graph name, so a model can never choose which customer's graph it reads.
Run: python -m app.mcp_server.server   (stdio transport)
"""

import os

from mcp.server.mcpserver import MCPServer

from app.graph.client import TenantGraph, rows

server = MCPServer(
    name="leaktrace",
    instructions="Domain tools over the LeakTrace flow-network graph. Every answer comes from FalkorDB queries.",
)


def _graph() -> TenantGraph:
    return TenantGraph(os.environ["LEAKTRACE_TENANT"])


@server.tool()
def find_suspects() -> dict:
    """Look for likely leak locations: pipe sections in zones with an active leak alarm, ranked by
    leak alarms on the section itself and pressure anomalies downstream of it. Use first when a
    leak alarm or a report of water is the only lead."""
    return {"suspects": rows(_graph().read("q1_find_suspects"))}


@server.tool()
def trace_impact(segment_id: str) -> dict:
    """Trace what a problem on one pipe section affects: racks or other consumers downstream (with
    criticality, required flow, workloads and owning teams) and consumers in the same or adjacent
    zones that water could reach (with their power feeds). Use once a suspect section is known."""
    g = _graph()
    return {
        "segment": segment_id,
        "downstream": rows(g.read("q2_trace_impact", {"segment": segment_id})),
        "exposure": rows(g.read("q3_exposure", {"segment": segment_id})),
    }


@server.tool()
def execution_status(decision_id: str) -> dict:
    """Read-only: where a committed decision stands (proposed, approved, executing, verifying, verified,
    failed, rolling back, rolled back), its authority level, each valve step and its state, how many
    valve actions were recorded and the verification results. It never approves, executes or undoes
    anything; those need a person or auto mode through the API."""
    out = rows(_graph().read("execution_status_read", {"id": decision_id}))
    if not out:
        return {"decision": decision_id, "found": False}
    r = out[0]
    r["steps"] = sorted(r["steps"], key=lambda s: (s["phase"], s["seq"]))
    return {"found": True, **r}


if __name__ == "__main__":
    server.run("stdio")
