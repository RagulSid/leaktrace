"""/health and what a FalkorDB failure says: "not reachable" (no server at host:port) versus "graph empty" (the
server answers but the customer's graph is missing or wiped), in the 503 body and the server log, never in the
plain words on screen; /health gives two yes/no answers with no ids or secrets."""

import logging
import socket

import pytest
from fastapi.testclient import TestClient

from app import config
from app.api.auth import issue_token
from app.api.main import app
from app.graph import client as graph_client
from app.graph.client import GraphUnavailable, TenantGraph
from scenario_generator.run import Session, run
from tests.conftest import fresh_tenant

PASSWORD = "practice-only-password"


@pytest.fixture
def demo(monkeypatch):
    t = fresh_tenant()
    run("s1", t, seed=2, reset=True, password=PASSWORD)
    monkeypatch.setattr(config, "DEMO_TENANT", t)
    yield t, TestClient(app)
    TenantGraph(t).delete()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_health_when_up_and_seeded(demo):
    t, c = demo
    r = c.get("/health")
    assert r.status_code == 200 and r.json() == {"falkordb_reachable": True, "demo_seeded": True}
    assert t not in r.text and "lt_" not in r.text and PASSWORD not in r.text


def test_missing_demo_graph_says_graph_empty_and_unknown_customer_still_looks_like_a_wrong_password(monkeypatch, caplog):
    t = fresh_tenant()  # never created
    monkeypatch.setattr(config, "DEMO_TENANT", t)
    c = TestClient(app)
    assert c.get("/health").status_code == 503 and c.get("/health").json() == {"falkordb_reachable": True, "demo_seeded": False}
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        r = c.post("/auth/login", json={"tenant": t, "username": "operator1", "password": "x"})
    b = r.json()
    assert r.status_code == 503 and b["error"] == "graph_unavailable" and b["reason"] == "graph_empty"
    assert (b["host"], b["port"], b["graph"]) == (config.FALKORDB_HOST, config.FALKORDB_PORT, f"lt_{t}")
    line = caplog.text
    assert "graph empty" in line and f"graph=lt_{t}" in line and f"port={config.FALKORDB_PORT}" in line
    assert "scenario_generator.demo" in line  # the fix is in the log
    # any other customer name: same answer as a wrong password (no way to learn which customers exist)
    other = c.post("/auth/login", json={"tenant": fresh_tenant(), "username": "operator1", "password": "x"})
    assert other.status_code == 401


def test_wiped_graph_after_sign_in_is_graph_empty_not_an_empty_queue(demo):
    t, c = demo
    sess = Session(t, PASSWORD)
    assert sess.get("/problems", "operator1")  # one problem before the wipe
    TenantGraph(t)._g.query("MATCH (n) DETACH DELETE n")  # what a crash before the last save leaves behind
    b = sess.get("/problems", "operator1", expect=503)
    assert b["reason"] == "graph_empty" and b["graph"] == f"lt_{t}"
    assert c.get("/health").json() == {"falkordb_reachable": True, "demo_seeded": False}
    r = c.post("/auth/login", json={"tenant": t, "username": "operator1", "password": PASSWORD})
    assert r.status_code == 503 and r.json()["reason"] == "graph_empty"


def test_not_reachable_names_host_port_and_graph(monkeypatch, caplog):
    token, _ = issue_token("operator1", "operator", "demo")
    port = _free_port()
    monkeypatch.setattr(config, "FALKORDB_PORT", port)
    graph_client.get_db.cache_clear()
    try:
        c = TestClient(app)
        h = c.get("/health")
        assert h.status_code == 503 and h.json() == {"falkordb_reachable": False, "demo_seeded": False}
        with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
            r = c.get("/problems", headers={"Authorization": f"Bearer {token}"})
        b = r.json()
        assert r.status_code == 503 and b["reason"] == "not_reachable"
        assert (b["host"], b["port"], b["graph"]) == (config.FALKORDB_HOST, port, "lt_demo")
        assert "password" not in r.text.lower()
        assert "not reachable" in caplog.text and f"port={port}" in caplog.text and "graph=lt_demo" in caplog.text
        assert "docker compose up -d" in caplog.text
    finally:
        monkeypatch.undo()
        graph_client.get_db.cache_clear()


def test_graph_unavailable_carries_where(monkeypatch):
    e = GraphUnavailable("x", reason="graph_empty", graph="lt_x")
    assert e.where() == {"reason": "graph_empty", "host": config.FALKORDB_HOST, "port": config.FALKORDB_PORT, "graph": "lt_x"}
