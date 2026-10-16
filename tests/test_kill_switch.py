"""Without FalkorDB nothing works: investigation, decisions, reports and login fail loudly (503 / exit 2).

Two versions:
  * always: the app is pointed at a port where nothing listens;
  * LEAKTRACE_KILLSWITCH_DOCKER=1: the real container is stopped after a full S1 run, the same calls
    are repeated (an existing decision is NOT served from anywhere else), then the container is restarted;
    and stopped in the middle of an execution: nothing half-applied is ever reported as verified, and the
    execution resumes cleanly after the restart.
"""

import os
import socket
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from app import config
from app.api.auth import issue_token
from app.api.main import app
from app.graph import client as graph_client
from scenario_generator.field import FieldWorker
from scenario_generator.plant import Plant
from scenario_generator.run import PACK, Session
from scenario_generator.run import run as run_scenario
from tests.conftest import ROOT, fresh_tenant


def _dead_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def graph_down(monkeypatch):
    monkeypatch.setattr(config, "FALKORDB_PORT", _dead_port())
    graph_client.get_db.cache_clear()
    yield
    monkeypatch.undo()
    graph_client.get_db.cache_clear()


def _headers(role: str, tenant: str = "demo") -> dict:
    return {"Authorization": f"Bearer {issue_token('someone', role, tenant)[0]}"}


def test_api_fails_loudly_without_falkordb(graph_down):
    c = TestClient(app)
    calls = [
        ("post", "/incidents/INC-000000/investigate", "operator", None),
        ("get", "/decisions/DEC-00000000", "operator", None),
        ("get", "/incidents", "operator", None),
        ("post", "/reports", "staff", {"text": "water under rack A1"}),
        ("post", "/readings", "integration", {"readings": [{"id": "LS-A1", "ts": 1.0, "state": "ALARM"}]}),
        ("post", "/decisions/DEC-00000000/approve", "operator", {}),
        ("post", "/decisions/DEC-00000000/reject", "operator", {}),
        ("post", "/decisions/DEC-00000000/execute", "operator", None),
        ("get", "/decisions/DEC-00000000/status", "operator", None),
        ("post", "/decisions/DEC-00000000/verify", "operator", None),
        ("post", "/decisions/DEC-00000000/rollback", "operator", {}),
        ("post", "/decisions/DEC-00000000/replan", "operator", None),
        ("get", "/decisions/DEC-00000000/audit", "operator", None),
        ("post", "/tasks/claim", "tech", {}),
        ("post", "/tasks/TSK-00000000/result", "tech", {"idempotency_key": "k", "outcome": "done", "observed_state": "open"}),
    ]
    for method, path, role, body in calls:
        r = getattr(c, method)(path, headers=_headers(role), **({"json": body} if body is not None else {}))
        assert r.status_code == 503, (path, r.status_code, r.text)
        assert r.json()["error"] == "graph_unavailable"
    r = c.post("/auth/login", json={"tenant": "demo", "username": "operator1", "password": "x"})
    assert r.status_code == 503


@pytest.mark.parametrize("args", [
    ["investigate", "--tenant", "demo", "--incident", "INC-000000"],
    ["approve", "--tenant", "demo", "--as", "operator2", "--decision", "DEC-00000000"],
    ["execute", "--tenant", "demo", "--as", "operator1", "--decision", "DEC-00000000"],
    ["status", "--tenant", "demo", "--as", "operator1", "--decision", "DEC-00000000"],
])
def test_cli_fails_loudly_without_falkordb(args):
    env = {**os.environ, "FALKORDB_PORT": str(_dead_port())}
    p = subprocess.run([sys.executable, "-m", "app.cli", *args], cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=120)
    assert p.returncode == 2
    assert "FalkorDB is not reachable" in p.stderr
    assert p.stdout.strip() == ""


def _docker(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120)


def _wait_ping(timeout_s: float = 60) -> None:
    end = time.time() + timeout_s
    while time.time() < end:
        if "PONG" in _docker("exec", "leaktrace-falkordb", "redis-cli", "PING").stdout:
            return
        time.sleep(1)
    raise RuntimeError("FalkorDB did not come back")


@pytest.mark.skipif(os.getenv("LEAKTRACE_KILLSWITCH_DOCKER") != "1", reason="stops the real container; opt-in")
def test_real_container_stop_breaks_everything():
    tenant = fresh_tenant()
    out = run_scenario("s1", tenant, seed=3, reset=True)
    did, incident = out["decision"]["decision_id"], out["incident"]
    c = TestClient(app)
    h = {"Authorization": f"Bearer {issue_token('operator1', 'operator', tenant)[0]}"}
    assert c.get(f"/decisions/{did}", headers=h).status_code == 200
    try:
        assert _docker("stop", "leaktrace-falkordb").returncode == 0
        graph_client.get_db.cache_clear()
        assert c.get(f"/decisions/{did}", headers=h).status_code == 503
        assert c.post(f"/incidents/{incident}/investigate", headers=h).status_code == 503
        assert c.get("/incidents", headers=h).status_code == 503
    finally:
        _docker("start", "leaktrace-falkordb")
        _wait_ping()
        graph_client.get_db.cache_clear()
    r = c.get(f"/decisions/{did}", headers=h)  # data is back from the volume, read from FalkorDB again
    assert r.status_code == 200 and r.json()["chosen"] == out["decision"]["chosen"]
    graph_client.TenantGraph(tenant).delete()


@pytest.mark.skipif(os.getenv("LEAKTRACE_KILLSWITCH_DOCKER") != "1", reason="stops the real container; opt-in")
def test_container_stop_mid_execution_never_reports_verified():
    import json

    tenant, password = fresh_tenant(), "practice-only-password"
    out = run_scenario("s1", tenant, seed=3, reset=True, password=password)
    did = out["decision"]["decision_id"]
    sess = Session(tenant, password)
    sess.post(f"/decisions/{did}/approve", "operator2")
    sess.post(f"/decisions/{did}/execute", "operator1")
    plant = Plant(json.loads(PACK.read_text(encoding="utf-8")), seed=3, leak_segment="SEG-A1",
                  leak_flow=out["leak_flow"])
    crew = FieldWorker(sess, "tech1", plant, lease_s=300)
    assert crew.work_one()["response"]["status"] == "executing"  # step 1 recorded
    t2 = crew.claim()  # step 2: the valve moves, then FalkorDB goes away before the report lands
    res = plant.command(t2["idempotency_key"], t2["valve"], t2["target"])
    body = {"idempotency_key": t2["idempotency_key"], "outcome": "done", "observed_state": res["observed"]}
    try:
        assert _docker("stop", "leaktrace-falkordb").returncode == 0
        graph_client.get_db.cache_clear()
        assert sess.post(f"/tasks/{t2['id']}/result", "tech1", body, expect=503)["error"] == "graph_unavailable"
        assert sess.get(f"/decisions/{did}/status", "operator1", expect=503)["error"] == "graph_unavailable"
        assert sess.post(f"/decisions/{did}/verify", "operator1", expect=503)
    finally:
        _docker("start", "leaktrace-falkordb")
        _wait_ping()
        graph_client.get_db.cache_clear()
    st = sess.get(f"/decisions/{did}/status", "operator1")
    assert st["status"] == "executing" and st["verification"] is None  # nothing claimed it worked
    assert [(t["status"], t["owner"]) for t in st["tasks"]] == [("done", "tech1"), ("claimed", "tech1"), ("pending", None)]
    assert len(st["actions"]) == 1
    # the crew phone retries the same report: applied once, and the plan carries on
    assert sess.post(f"/tasks/{t2['id']}/result", "tech1", body)["duplicate"] is False
    crew.drain()
    sess.post("/readings", "meters1", {"readings": plant.readings(time.time()), "source": "synthetic"})
    st = sess.get(f"/decisions/{did}/status", "operator1")
    assert st["status"] == "verified" and len(st["actions"]) == 3 and len(plant.moves) == 3
    graph_client.TenantGraph(tenant).delete()
