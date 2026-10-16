"""How it works honesty (BUILD_PROMPT 16, test 16): live numbers that change with the data, the query text shown
byte for byte equal to the text that runs, read-only searches only, the demo customer only, and an error with
no numbers when FalkorDB is down."""

import socket

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ResponseError

from app import config
from app.api import how_it_works
from app.api.main import app
from app.graph import client as graph_client
from app.graph import queries
from app.graph.client import TenantGraph, rows
from scenario_generator.run import run
from tests.conftest import fresh_tenant

PASSWORD = "practice-only-password"


@pytest.fixture
def demo(monkeypatch):
    """A fresh customer with S1 decided, used as the demo customer."""
    t = fresh_tenant()
    run("s1", t, seed=2, reset=True, password=PASSWORD)
    monkeypatch.setattr(config, "DEMO_TENANT", t)
    monkeypatch.setattr(how_it_works, "run_limit", how_it_works.RateLimit(1000))
    yield TestClient(app), TenantGraph(t)
    TenantGraph(t).delete()


def test_numbers_are_live_and_change_with_the_data(demo):
    c, tg = demo
    s = c.get("/how-it-works/summary").json()
    live = rows(tg.read("stats"))[0]
    assert (s["nodes"], s["links"]) == (live["nodeCount"], live["relCount"]) and s["connected"] is True
    assert s["kinds"] == len(rows(tg.read("hiw_labels"))[0]["labels"])
    c.post("/public/reports", json={"kinds": ["water"], "where": "under Rack A1 in Row A"})
    after = c.get("/how-it-works/summary").json()
    assert after["nodes"] > s["nodes"] and after["links"] > s["links"]
    report = c.post("/how-it-works/run/report").json()
    assert report["rows"] and report["row_count"] == len(rows(tg.read("hiw_report_links", report["params"])))


def test_query_text_shown_is_the_text_that_runs(demo):
    c, tg = demo
    steps = c.get("/how-it-works/steps").json()
    assert steps["problem"]["segment"] == "SEG-A1"
    assert [s["key"] for s in steps["steps"]] == ["report", "balance", "affected", "plans", "authority", "remember"]
    for s in steps["steps"]:
        assert s["query"] == queries.load(s["query_name"])  # byte for byte
        assert s["plan"]  # GRAPH.EXPLAIN of that same text
        graph_client.QUERY_LOG.clear()
        r = c.post(f"/how-it-works/run/{s['key']}").json()
        assert r["query"] == queries.load(s["query_name"]) and r["params"] == s["params"]
        ran = [e for e in graph_client.QUERY_LOG if e.query == s["query_name"]]
        assert ran and all(e.mode == "read" and e.text == r["query"] for e in ran)  # GRAPH.RO_QUERY, same text
        assert r["profile"] and len(r["rows"]) <= how_it_works.ROW_CAP
    flow = c.post("/how-it-works/run/plans").json()
    assert flow["query_name"] == "max_flow" and flow["rows"][0]["maxFlow"] >= 0  # algo.maxFlow, live


def test_writes_through_the_read_path_are_rejected(demo):
    _, tg = demo
    with pytest.raises(ResponseError, match="read-only"):
        tg._run("probe", "CREATE (:Probe)", None, "read", 2000)
    assert tg._g.ro_query("MATCH (p:Probe) RETURN count(p)").result_set == [[0]]


def test_visitors_choose_a_step_never_a_query_or_a_customer(demo):
    c, tg = demo
    assert c.post("/how-it-works/run/anything").status_code == 404
    assert c.post("/how-it-works/run/report", json={"query": "MATCH (n) DETACH DELETE n"}).status_code == 200
    assert rows(tg.read("stats"))[0]["nodeCount"] > 0
    other = fresh_tenant()
    try:
        run("s1", other, seed=3, reset=True, password=PASSWORD)
        a = c.get("/how-it-works/summary").json()
        b = c.get(f"/how-it-works/summary?tenant={other}").json()  # ignored: demo customer only
        assert a["nodes"] == b["nodes"] == rows(tg.read("stats"))[0]["nodeCount"]
    finally:
        TenantGraph(other).delete()
    src = (how_it_works.__file__ and open(how_it_works.__file__, encoding="utf-8").read())
    assert "list_graphs" not in src and "GRAPH.LIST" not in src.replace("never lists graphs", "")


def test_run_is_rate_limited(demo, monkeypatch):
    c, _ = demo
    monkeypatch.setattr(how_it_works, "run_limit", how_it_works.RateLimit(2))
    codes = [c.post("/how-it-works/run/authority").status_code for _ in range(4)]
    assert codes.count(429) >= 1


def test_falkordb_down_means_an_error_and_no_numbers(monkeypatch):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    monkeypatch.setattr(config, "FALKORDB_PORT", port)
    graph_client.get_db.cache_clear()
    try:
        c = TestClient(app)
        for path in ("/how-it-works/summary", "/how-it-works/steps", "/how-it-works/features"):
            r = c.get(path)
            assert r.status_code == 503 and r.json()["error"] == "graph_unavailable"
            assert not any(k in r.json() for k in ("nodes", "links", "kinds", "steps", "features"))
        assert c.post("/how-it-works/run/report").status_code == 503
    finally:
        monkeypatch.undo()
        graph_client.get_db.cache_clear()
