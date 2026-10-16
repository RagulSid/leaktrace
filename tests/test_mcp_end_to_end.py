"""One MCP tool call end to end: MCP client -> our tool server (stdio subprocess) -> FalkorDB -> result."""

import asyncio
import json
import os
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from tests.conftest import ROOT


def _params(tenant: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server.server"],
        env={"LEAKTRACE_TENANT": tenant, **{k: os.environ[k] for k in ("FALKORDB_HOST", "FALKORDB_PORT") if k in os.environ}},
        cwd=str(ROOT),
    )


async def _call(tenant: str, tool: str = "trace_impact", args: dict | None = None):
    async with Client(_params(tenant), read_timeout_seconds=30) as client:
        tools = await client.list_tools()
        result = await client.call_tool(tool, args if args is not None else {"segment_id": "SEG-A1"})
        return tools, result


def test_trace_impact_over_mcp(dc):
    tools, result = asyncio.run(_call(dc.tenant))
    names = {t.name for t in tools.tools}
    assert {"find_suspects", "trace_impact"} <= names
    for t in tools.tools:  # the model can never pick a tenant or graph
        assert not ({"tenant", "graph", "graph_name"} & set(t.input_schema.get("properties", {})))
    assert not result.is_error, result
    data = result.structured_content or json.loads(result.content[0].text)
    assert [r["consumer"] for r in data["downstream"]] == ["RACK-A1", "RACK-A2"]
    assert data["downstream"][0]["owners"] == ["T-ML"]
    assert {r["consumer"] for r in data["exposure"]} == {"RACK-A1", "RACK-A2"}


def test_execution_status_over_mcp_is_read_only():
    from app.graph.client import TenantGraph
    from scenario_generator.run import run_execution
    from tests.conftest import fresh_tenant

    tenant = fresh_tenant()
    try:
        r = run_execution("s1", "happy", tenant, 2, reset=True)
        tools, result = asyncio.run(_call(tenant, "execution_status", {"decision_id": r["decision"]}))
        names = {t.name for t in tools.tools}
        assert names == {"find_suspects", "trace_impact", "execution_status", "ask_leaktrace"}  # nothing that approves or moves valves
        data = result.structured_content or json.loads(result.content[0].text)
        assert data["found"] and data["status"] == "verified" and data["actions"] == 3
        assert [(s["seq"], s["valve"], s["status"]) for s in data["steps"]] == [
            (1, "V-09", "done"), (2, "V-01", "done"), (3, "V-07", "done")]
        before = TenantGraph(tenant)._g.ro_query("MATCH (a:AuditEvent) RETURN count(a)").result_set
        asyncio.run(_call(tenant, "execution_status", {"decision_id": r["decision"]}))
        assert TenantGraph(tenant)._g.ro_query("MATCH (a:AuditEvent) RETURN count(a)").result_set == before
    finally:
        TenantGraph(tenant).delete()
