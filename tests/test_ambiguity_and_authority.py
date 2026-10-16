"""Weak evidence never leads to action; the same engine gives L2 on a low-risk leak and L3 on S1;
each envelope condition on its own turns L2 into L3."""

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.cli import bootstrap
from app.domain.authority import AuthorityInput, compute
from app.graph.client import TenantGraph, rows
from scenario_generator.run import run as run_scenario
from scenario_generator.scenarios import T0
from tests.conftest import DATACENTER_PACK, fresh_tenant

PASSWORD = "practice-only-password"


@pytest.fixture
def api_tenant():
    c, t = TestClient(app), fresh_tenant()
    bootstrap(t, password=PASSWORD)
    tok = {}

    def h(user):
        if user not in tok:
            tok[user] = c.post("/auth/login", json={"tenant": t, "username": user, "password": PASSWORD}).json()["token"]
        return {"Authorization": f"Bearer {tok[user]}"}

    assert c.post("/assets/import", json=json.loads(DATACENTER_PACK.read_text(encoding="utf-8")),
                  headers=h("manager1")).status_code == 200
    yield c, t, h
    TenantGraph(t).delete()


def _readings(c, h, readings):
    r = c.post("/readings", json={"readings": readings}, headers=h("meters1"))
    assert r.status_code == 200, r.text
    return r.json()


def _no_plans(tg, incident):
    return tg._g.ro_query("MATCH (:Incident {id:$i})-[:HAS_OPTION]->(o) RETURN count(o)", {"i": incident}).result_set == [[0]]


def test_single_leak_alarm_alone_requests_evidence(api_tenant):
    c, t, h = api_tenant
    inc = _readings(c, h, [{"id": "LS-A1", "ts": T0, "state": "ALARM"}])["incidents"]["LS-A1"]
    d = c.post(f"/incidents/{inc}/investigate", headers=h("operator1")).json()
    assert d["kind"] == "request_evidence" and d["reason"] == "low_confidence"
    assert d["suspect"]["confidence"]["score"] == 0.35
    assert set(d["suspect"]["confidence"]["kinds"]) == {"leak_alarm"}
    assert "evaluate_option" not in d["tool_sequence"]
    assert _no_plans(TenantGraph(t), inc)
    task = TenantGraph(t)._g.ro_query("MATCH (k:Task {kind:'inspect'})-[:FOR]->(:Incident {id:$i}) RETURN k.status",
                                      {"i": inc}).result_set
    assert task == [["open"]]


def test_single_pressure_anomaly_alone_requests_evidence(api_tenant):
    c, t, h = api_tenant
    inc = _readings(c, h, [{"id": "PS-MA", "ts": T0, "state": "ANOMALY"}])["incidents"]["PS-MA"]
    d = c.post(f"/incidents/{inc}/investigate", headers=h("operator1")).json()
    assert d["kind"] == "request_evidence"
    assert d["suspect"]["confidence"]["score"] <= 0.4


def test_balanced_meters_contradict_a_report(api_tenant):
    c, t, h = api_tenant
    out = run_scenario("s2", t, seed=5, password=PASSWORD)
    d = out["decision"]
    assert d["kind"] == "request_evidence" and d["reason"] == "contradiction"
    assert d["suspect"]["balance"]["status"] == "balanced"
    assert "evaluate_option" not in d["tool_sequence"]


def test_s1_and_s2_tool_sequences_differ(api_tenant):
    c, t, h = api_tenant
    s2 = run_scenario("s2", t, seed=5, password=PASSWORD)["decision"]["tool_sequence"]
    other = fresh_tenant()
    try:
        s1 = run_scenario("s1", other, seed=5, reset=True)["decision"]["tool_sequence"]
    finally:
        TenantGraph(other).delete()
    assert s1 != s2
    assert {"trace_impact", "generate_options", "evaluate_option", "compute_authority"} <= set(s1)
    assert not {"generate_options", "evaluate_option", "compute_authority"} & set(s2)
    assert "request_evidence" in s2


def _low_risk_leak(c, h):
    """Leak on the rack A2 feed (SEG-A3): alarm on that pipe, row A inflow 10 high, one report."""
    meters = {"FM-RA1": 20.0, "FM-RA2": 15.0, "FM-RB1": 20.0, "FM-RB2": 15.0, "FM-A-IN": 45.0, "FM-B-IN": 35.0, "FM-01": 80.0}
    readings = [{"id": k, "ts": T0, "value": v} for k, v in meters.items()] + [{"id": "LS-A3", "ts": T0, "state": "ALARM"}]
    inc = _readings(c, h, readings)["incidents"]["LS-A3"]
    c.post("/reports", json={"text": "Water on the floor near Rack A2"}, headers=h("staff1"))
    return inc


def test_low_risk_leak_is_handled_automatically(api_tenant):
    c, t, h = api_tenant
    inc = _low_risk_leak(c, h)
    d = c.post(f"/incidents/{inc}/investigate", headers=h("operator1")).json()
    assert d["suspect"]["segment"] == "SEG-A3" and d["suspect"]["confidence"]["score"] == 0.7
    assert d["plans"][0]["label"] == "close V-04" and d["plans"][0]["passed"]
    assert d["authority"] == {"level": "L2", "failed": [], "passed": [
        "policy_active", "confidence", "no_starved_critical", "criticality_ceiling", "reversible_feasible",
        "operation_limit", "no_life_safety", "rollback_and_check"]}
    assert d["fallback"] == d["plans"][1]["id"] and d["plans"][1]["label"] == "close V-04, open V-09"


def test_paused_auto_mode_turns_the_same_case_into_l3(api_tenant):
    c, t, h = api_tenant
    TenantGraph(t)._g.query("MATCH (p:AuthorityPolicy {id:'POL-DC-1'}) SET p.frozen = true")
    inc = _low_risk_leak(c, h)
    d = c.post(f"/incidents/{inc}/investigate", headers=h("operator1")).json()
    assert d["authority"]["level"] == "L3"
    assert d["authority"]["failed"] == [{"code": "policy_active", "reason": "auto_mode_paused"}]


def test_stuck_valve_in_memory_fails_feasibility(api_tenant):
    c, t, h = api_tenant
    TenantGraph(t)._g.query(
        "MATCH (v:Valve {id:'V-09'}) CREATE (:Fact {id:'F-V09', kind:'stuck', status:'active', "
        "statement:'V-09 failed to open on cold start', source:'synthetic'})-[:ABOUT]->(v)")
    out = run_scenario("s1", t, seed=2, password=PASSWORD)
    d = out["decision"]
    plans = {p["label"]: p for p in d["plans"]}
    rescue = plans["close V-01 + V-07, open V-09"]
    assert rescue["failed_checks"] == ["feasible"]
    feas = next(c["detail"] for c in rescue["checks"] if c["code"] == "feasible")
    assert feas["stuck"] == [{"valve": "V-09", "facts": ["F-V09"]}]
    assert d["kind"] == "escalate" and d["chosen"] is None  # nothing else passes: people must decide
    assert d["authority"]["failed"] == [{"code": "no_plan_passes"}]


# ---- pure authority function: each condition alone flips L2 to L3

POLICY = {"id": "P", "status": "active", "frozen": False, "min_confidence": 0.7, "max_auto_criticality": 3,
          "max_auto_operations": 2, "rate_limit_per_zone_per_hour": 3}
OK = AuthorityInput(policy=POLICY, confidence=0.8, contradictions=0, starved_critical=0, max_affected_criticality=2,
                    reversible_feasible=True, op_count=1, recent_zone_actions=0)

FLIPS = {
    "policy_active": [replace(OK, policy=None), replace(OK, policy={**POLICY, "frozen": True}),
                      replace(OK, policy={**POLICY, "status": "retired"})],
    "confidence": [replace(OK, confidence=0.69), replace(OK, contradictions=1)],
    "no_starved_critical": [replace(OK, starved_critical=1)],
    "criticality_ceiling": [replace(OK, max_affected_criticality=4)],
    "reversible_feasible": [replace(OK, reversible_feasible=False)],
    "operation_limit": [replace(OK, op_count=3), replace(OK, recent_zone_actions=3)],
    "rollback_and_check": [replace(OK, rollback_defined=False), replace(OK, verification_defined=False)],
}


def test_all_conditions_hold_gives_l2():
    r = compute(OK)
    assert r.level == "L2" and r.failed == []


@pytest.mark.parametrize("code,case", [(k, c) for k, cs in FLIPS.items() for c in cs])
def test_each_condition_alone_flips_to_l3(code, case):
    r = compute(case)
    assert r.level == "L3"
    if case.policy is None or case.policy.get("status") != "active":
        assert "policy_active" in r.failed_codes
    else:
        assert r.failed_codes == [code]


def test_life_safety_effect_is_l4_even_when_all_else_holds():
    r = compute(replace(OK, l4_effects=["evacuate_zone"]))
    assert r.level == "L4" and r.failed_codes == ["no_life_safety"]


def test_edge_values_pass():
    assert compute(replace(OK, confidence=0.7, max_affected_criticality=3, op_count=2, recent_zone_actions=2)).level == "L2"
