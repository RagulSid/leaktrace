"""S3 and restart recall: a valve recorded stuck changes the next plan after every helper process is gone.

Each helper round runs as a new operating-system process (python -m app.agents.worker), so nothing can be
remembered except what is in FalkorDB.
"""

import json
import time

import pytest

from app.graph.client import TenantGraph, rows
from scenario_generator.run import Session, _latest_decision, run_helper_round, run_helpers
from scenario_generator.scenarios import T0, _batch, _meters
from tests.conftest import fresh_tenant

PASSWORD = "practice-only-password"
NORMAL = {"LS-A1": "OK", "LS-A3": "OK", "LS-B1": "OK", "PS-MA": "OK", "PS-MB": "OK"}


@pytest.fixture
def tenant():
    t = fresh_tenant()
    yield t
    TenantGraph(t).delete()


def test_stuck_valve_is_recalled_after_restart_and_changes_the_plan(tenant):
    import random

    # first problem: approved plan, V-09 does not move, the crew's report becomes a fact
    first = run_helpers("s1", "stuck_v09", tenant, 4, reset=True, password=PASSWORD, process=True)
    assert first["final"]["status"] == "failed"
    pids_first = {r["pid"] for r in first["rounds"]}
    tg, sess = TenantGraph(tenant), Session(tenant, PASSWORD)
    fact = tg._g.ro_query("MATCH (f:Fact {kind:'stuck', status:'active'})-[:ABOUT]->(:Valve {id:'V-09'}) "
                          "RETURN f.id").result_set
    assert len(fact) == 1
    fact_id = fact[0][0]
    # people deal with it: undo (nothing moved), fix the leak by hand, close the problem, reset the sensors
    did = first["final"]["decision"]
    sess.post(f"/decisions/{did}/rollback", "operator1", {"reason": "V-09 seized"})
    sess.post(f"/incidents/{first['incident']}/close", "operator1", {"reason": "pipe patched by hand"})
    rng = random.Random(99)
    sess.post("/readings", "meters1", {"readings": _batch(time.time(), _meters(rng, 0.0), NORMAL)})

    # every helper process is gone. A new leak on the same pipe opens a new problem.
    leak = _batch(time.time(), _meters(rng, 11.0), {**NORMAL, "LS-A1": "ALARM", "PS-MA": "ANOMALY"})
    new_inc = sess.post("/readings", "meters1", {"readings": leak})["incidents"]["LS-A1"]
    assert new_inc != first["incident"]
    second = run_helper_round(tenant, process=True)
    assert second["pid"] not in pids_first  # a different process: nothing carried over in memory

    recall = [json.loads(e["summary"]) for e in rows(tg.read("episodes_for_incident", {"incident": new_inc}))
              if e["kind"] == "agent_step" and e["tool"] == "recall_memory"]
    assert recall and any("V-09 did not move" in f for a in recall[0]["facts"] for f in a["facts"])
    d = _latest_decision(sess, new_inc)
    assert d["kind"] == "escalate"  # without the fact this is the approved rescue plan (S1)
    explain = sess.get(f"/decisions/{d['decision']}", "operator1")
    rescue = next(p for p in explain["plans"] if p["label"] == "close V-01 + V-07, open V-09")
    feas = next(c for c in rescue["checks"] if c["code"] == "feasible")
    assert feas["detail"]["stuck"] == [{"valve": "V-09", "facts": [fact_id]}]
    agents = {a["id"]: a for a in rows(tg.read("agents_list"))}
    assert agents["planner"]["pid"] == second["pid"]
