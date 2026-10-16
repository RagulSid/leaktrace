"""Foundation checks against a live FalkorDB: tenancy, schema, seed load, saved queries, read-only path."""

import pytest
from redis.exceptions import ResponseError

from app.graph import queries
from app.graph.client import QUERY_LOG, TenantGraph, rows
from app.graph.tenancy import InvalidTenant, graph_name


def test_graph_name_validation():
    assert graph_name("demo") == "lt_demo"
    for bad in ["", "Demo", "1abc", "a-b", "a b", "x" * 40, "demo}", None]:
        with pytest.raises(InvalidTenant):
            graph_name(bad)


def test_every_saved_query_loads():
    assert len(queries.names()) >= 15
    for name in queries.names():
        text = queries.load(name)
        assert text and not text.startswith("//"), name


def test_seed_pack_loads(dc):
    stats = rows(dc.read("stats"))[0]
    assert stats["nodeCount"] == 49  # 47 network and registry nodes + leak sensor LS-A3 + policy POL-DC-1
    assert stats["labels"]["Valve"] == 9 and stats["labels"]["Consumer"] == 4
    assert stats["relTypes"]["FLOWS_TO"] == 45  # 25 links, 20 of them two-way
    synthetic = dc._g.ro_query("MATCH (n:Entity) WHERE n.source <> 'synthetic' RETURN count(n)").result_set[0][0]
    assert synthetic == 0


def test_tenant_graphs_are_separate(make_graph):
    a, b = make_graph(), make_graph()
    a.write("task_create", {"ids": ["only-in-a"], "kind": "probe", "source": "synthetic"})
    assert rows(a.read("task_status", {"ids": ["only-in-a"]}))[0]["status"] == "open"
    assert rows(b.read("task_status", {"ids": ["only-in-a"]})) == []


def test_ro_query_rejects_writes(dc):
    with pytest.raises(ResponseError, match="read-only"):
        dc._run("probe_write", "CREATE (:Task {id:'x'})", None, "read", 1000)
    # the write did not happen
    assert rows(dc.read("task_status", {"ids": ["x"]})) == []


def test_read_timeout_is_enforced(dc):
    with pytest.raises(ResponseError, match="timed out"):
        dc._run("probe_slow", "UNWIND range(1, 5000000) AS x RETURN sum(x)", None, "read", 5)


def test_explain_profile_slowlog_stats(dc):
    plan = str(dc.explain("q2_trace_impact", {"segment": "SEG-A1"}))
    assert "Conditional Variable Length Traverse" in plan or "Traverse" in plan
    prof = dc.profile_read("q2_trace_impact", {"segment": "SEG-A1"})
    assert any("Records produced" in line and "Execution time" in line for line in prof.plan)
    assert prof.structured_plan.records_produced == 2  # RACK-A1 and RACK-A2
    assert isinstance(dc.slowlog(), list)
    stats = rows(dc.read("stats"))[0]
    assert stats["relCount"] == 91


def test_query_log_records_calls(dc):
    before = len(QUERY_LOG)
    dc.read("stats")
    entry = QUERY_LOG[-1]
    assert len(QUERY_LOG) == before + 1 or len(QUERY_LOG) == QUERY_LOG.maxlen
    assert entry.query == "stats" and entry.mode == "read" and entry.ms >= 0 and entry.graph == dc.name


def test_unknown_tenant_graph_reads_empty_not_other_tenant(dc):
    other = TenantGraph("t_never_created_x")
    with pytest.raises(ResponseError):
        other.read("stats")  # no graph yet: FalkorDB refuses rather than returning another tenant's data
