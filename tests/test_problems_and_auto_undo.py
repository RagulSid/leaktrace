"""A verified fix closes the problem, so a new alarm opens a new one; a sensor that stays wet does not.
After an automatic plan fails its check and is undone: the valve it closed is recorded, and the new plan
always needs a person."""

import json
import time

import pytest

from app.agents import investigate as investigation
from app.execution import service as execution
from app.graph.client import TenantGraph, rows
from scenario_generator.plant import Plant
from scenario_generator.run import PACK, Session, run, run_execution
from scenario_generator.scenarios import _batch, _meters
from tests.conftest import fresh_tenant

PASSWORD = "practice-only-password"
NORMAL = {"LS-A1": "OK", "LS-A3": "OK", "LS-B1": "OK", "PS-MA": "OK", "PS-MB": "OK"}


@pytest.fixture
def tenant():
    t = fresh_tenant()
    yield t
    TenantGraph(t).delete()


def _incident(tg, iid):
    return rows(tg.read("incident_get", {"id": iid}))[0]


def test_verified_fix_closes_the_problem_and_a_new_alarm_opens_a_new_one(tenant):
    r = run_execution("s1", "happy", tenant, 2, reset=True, password=PASSWORD)
    tg, inc = TenantGraph(tenant), r["investigation"]["incident"]
    assert r["final"]["status"] == "verified"
    i = tg._g.ro_query("MATCH (i:Incident {id:$i}) RETURN i.status, i.closed_by, i.closed_at IS NOT NULL",
                       {"i": inc}).result_set
    assert i == [["resolved", r["decision"], True]]
    sess = Session(tenant, PASSWORD)
    # the floor is still wet: the leak sensor keeps reporting ALARM; that is not a new problem
    wet = sess.post("/readings", "meters1", {"readings": [{"id": "LS-A1", "ts": time.time(), "state": "ALARM"}]})
    assert wet["incidents"] == {}
    assert len(sess.get("/incidents", "operator1")) == 1
    # the crew resets the sensor; a later alarm is a new problem with its own Intake step
    sess.post("/readings", "tech1", {"readings": [{"id": "LS-A1", "ts": time.time(), "state": "OK"}]})
    new = sess.post("/readings", "meters1", {"readings": [{"id": "LS-A1", "ts": time.time(), "state": "ALARM"}]})
    new_inc = new["incidents"]["LS-A1"]
    assert new_inc != inc and _incident(tg, new_inc)["status"] == "open"
    assert tg._g.ro_query("MATCH (t:Task {kind:'triage', status:'open'})-[:FOR]->(:Incident {id:$i}) RETURN count(t)",
                          {"i": new_inc}).result_set == [[1]]


def test_a_person_can_close_a_problem_but_not_while_a_plan_runs(tenant):
    out = run("s1", tenant, seed=3, reset=True, password=PASSWORD)
    sess, inc, did = Session(tenant, PASSWORD), out["incident"], out["decision"]["decision_id"]
    sess.post(f"/decisions/{did}/approve", "operator2")
    sess.post(f"/decisions/{did}/execute", "operator1")
    r = sess.post(f"/incidents/{inc}/close", "operator1", {"reason": "fixed by hand"}, expect=409)
    assert r["error"] == "execution_in_progress"
    assert sess.post(f"/incidents/{inc}/close", "staff1", {"reason": "fixed by hand"}, expect=403)
    # a second problem with a plan still waiting for approval: closing supersedes the plan
    other = fresh_tenant()
    try:
        o = run("s1", other, seed=4, reset=True, password=PASSWORD)
        s2 = Session(other, PASSWORD)
        closed = s2.post(f"/incidents/{o['incident']}/close", "manager1", {"reason": "pipe replaced by hand"})
        assert closed["status"] == "closed"
        assert s2.get(f"/decisions/{o['decision']['decision_id']}/status", "operator1")["status"] == "superseded"
        assert s2.post(f"/incidents/{o['incident']}/close", "manager1", {"reason": "again"}, expect=409)["error"] == "not_open"
        trail = TenantGraph(other)._g.ro_query("MATCH (a:AuditEvent {kind:'incident'})-[:OF]->(:Incident {id:$i}) "
                                               "RETURN a.actor, a.to_status, a.reason", {"i": o["incident"]}).result_set
        assert trail == [["manager1", "closed", "pipe replaced by hand"]]
    finally:
        TenantGraph(other).delete()


def test_failed_automatic_plan_records_the_valve_and_the_new_plan_goes_to_people(tenant):
    r = run_execution("s5", "passing_valve", tenant, 3, reset=True, password=PASSWORD)
    tg, old = TenantGraph(tenant), r["decision"]
    assert r["final"]["status"] == "rolled_back"
    fact = tg._g.ro_query(
        "MATCH (f:Fact)-[:ABOUT]->(:Valve {id:'V-04'}) MATCH (f)-[:EVIDENCED_BY]->(v:Verification)-[:VERIFIES]->(:Decision {id:$d}) "
        "RETURN f.id, f.kind, f.status, f.source, f.confidence", {"d": old}).result_set
    assert len(fact) == 1 and fact[0][1:] == ["stuck", "active", "verification", 0.6]
    new = tg._g.ro_query("MATCH (n:Decision)-[:SUPERSEDES]->(:Decision {id:$d}) RETURN n.id, n.kind, n.authority_level, "
                         "n.explain_json", {"d": old}).result_set
    assert len(new) == 1
    nid, kind, level, explain = new[0]
    record = json.loads(explain)
    assert level != "L2" and record["capped"]["previous"] == old
    assert record["capped"]["original_fallback"] is not None  # the plan it would have fallen back to
    # the fallback also closes V-04, which is now known not to seal, so people decide
    assert kind == "escalate"
    for p in record["plans"]:
        if "V-04" in p["label"] and p["label"].startswith("close"):
            feas = next(c for c in p["checks"] if c["code"] == "feasible")
            assert feas["detail"]["stuck"] == [{"valve": "V-04", "facts": [fact[0][0]]}]
    esc = [e for e in r["audit"] if e["reason"] == "escalated_to_people"]
    assert esc and esc[0]["detail"]["new_decision"] == nid
    # the helpers get a Dispatcher step for the new decision (jobs for people, then the report)
    assert tg._g.ro_query("MATCH (t:Task {kind:'dispatch'}) WHERE t.payload CONTAINS $n RETURN count(t)",
                          {"n": nid}).result_set == [[1]]


def test_a_capped_plan_that_still_passes_needs_approval(tenant):
    """The fallback 'escalated to approval': when the next plan still passes, it is committed, but never L2."""
    out = run("s5", tenant, seed=2, reset=True, password=PASSWORD, investigate=False)
    rec = investigation.run(TenantGraph(tenant), out["incident"], requested_by="auto",
                            cap={"reason": "automatic_plan_failed_its_check", "previous": "DEC-EARLIER"})
    assert rec["kind"] == "act" and rec["chosen"] is not None
    assert rec["authority"]["level"] == "L3"
    assert rec["authority"]["failed"] == [{"code": "auto_attempt_failed", "reason": "automatic_plan_failed_its_check",
                                           "previous": "DEC-EARLIER"}]


def test_several_closed_valves_are_only_suspects(tenant):
    """With more than one closed valve we cannot tell which leaks: 'suspect' facts, which do not block plans."""
    r = run_execution("s1", "happy", tenant, 1, reset=True, password=PASSWORD)
    tg = TenantGraph(tenant)
    x = execution.load(tg, r["decision"])["execution"]
    ver = r["final"]["verification"]["id"]
    assert execution._suspect_valves(tg, r["decision"], x, ["balance_restored"], ver) == ["V-01", "V-07"]
    kinds = tg._g.ro_query("MATCH (f:Fact)-[:ABOUT]->(v:Valve) RETURN v.id, f.kind ORDER BY v.id").result_set
    assert kinds == [["V-01", "suspect"], ["V-07", "suspect"]]
    flags = rows(tg.read("asset_flags", {"ids": ["V-01", "V-07"]}))
    assert all(f["stuck"] == [] or all(s["fact"] is None for s in f["stuck"]) for f in flags)


def test_plant_outflow_meter_after_a_leak_reads_only_what_reaches_the_rack():
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    plant = Plant(pack, seed=1, leak_segment="SEG-A3", leak_flow=10.0)
    v = {r["id"]: r.get("value") for r in plant.readings(1.0)}
    assert abs(v["FM-RA2"] - 15.0) <= 0.4 and abs(v["FM-A-IN"] - 45.0) <= 0.4
    # the scenario readings use the same meaning
    m = _meters(__import__("random").Random(1), 10.0)
    assert abs(m["FM-A-IN"] - (m["FM-RA1"] + m["FM-RA2"] + 10.0)) <= 0.4
    assert _batch(1.0, {"FM-RA2": 15.0}, NORMAL)[0] == {"id": "FM-RA2", "ts": 1.0, "value": 15.0}
