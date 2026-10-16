"""Carrying out decisions end to end, through the REST API, with simulated field crew and plant.

Every scenario runs the S1 (or S5) investigation, then the variant. The simulated plant computes flows on
its own (scenario_generator/plant.py); verification compares its readings with what the plan expected.
"""

import pytest

from app.domain import lifecycle
from app.graph.client import TenantGraph, rows
from scenario_generator.run import run_execution
from tests.conftest import fresh_tenant


@pytest.fixture
def tenant():
    t = fresh_tenant()
    yield t
    TenantGraph(t).delete()


def _transitions(audit):
    return [(e["from_status"], e["to_status"]) for e in audit if e["kind"] == "decision"]


def _all_legal(audit):
    return all(lifecycle.can(a, b) for a, b in _transitions(audit))


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_s1_approved_plan_is_verified_on_every_seed(tenant, seed):
    r = run_execution("s1", "happy", tenant, seed, reset=True)
    f = r["final"]
    assert f["status"] == "verified" and f["outcome"] == "verified" and f["authority_level"] == "L3"
    # make before break: the backup link opens first, so rack A1 is never cut off
    assert [(t["seq"], t["target"], t["valve"], t["status"]) for t in f["tasks"]] == [
        (1, "open", "V-09", "done"), (2, "closed", "V-01", "done"), (3, "closed", "V-07", "done")]
    assert [m["valve"] for m in r["plant_moves"]] == ["V-09", "V-01", "V-07"]
    v = {c["code"]: c for c in f["verification"]["checks"]}
    assert all(c["passed"] for c in v.values()), v
    assert v["leak_isolated"]["detail"]["method"] == "isolation_meters"
    assert v["leak_isolated"]["detail"]["values"]["FM-A-IN"] <= 2.0
    crit = v["critical_supplied"]["detail"]["consumers"]
    assert {c: x["expected"] for c, x in crit.items()} == {"RACK-A1": 20.0, "RACK-B1": 20.0}
    assert all(x["meters"][m] >= 18.0 for x in crit.values() for m in x["meters"])
    assert v["pressure_normal"]["detail"]["sensors"] == {"PS-MA": "OK"}
    assert v["balance_restored"]["detail"]["meter"] == "FM-01"
    # who did what, in order, and every step legal
    assert _transitions(r["audit"]) == [("proposed", "approved"), ("approved", "executing"),
                                        ("executing", "verifying"), ("verifying", "verified")]
    assert [e["actor"] for e in r["audit"] if e["kind"] == "decision"][:2] == ["operator2", "operator1"]
    # actions: one per move, each authorised by the approval, in the problem's zone
    acts = f["actions"]
    assert [(a["valve"], a["from_state"], a["to_state"]) for a in acts] == [
        ("V-09", "closed", "open"), ("V-01", "open", "closed"), ("V-07", "open", "closed")]
    assert {a["authorized_by"] for a in acts} == {f["approval"]["id"]}
    g = TenantGraph(tenant)
    assert dict(rows(g.read("valves_and_caps"))[0]["valves"]) == {
        "V-01": "closed", "V-07": "closed", "V-09": "open", "V-02": "open", "V-03": "open", "V-04": "open",
        "V-05": "open", "V-06": "open", "V-08": "open"}
    caps = dict(rows(g.read("valves_and_caps"))[0]["edges"])
    assert caps["f04"] == caps["f04_r"] == 0 and caps["f06"] == 0 and caps["f24"] == caps["f24_r"] == 40
    assert g._g.ro_query("MATCH (a:Action {zone: 'Z-A'})-[:AUTHORIZED_BY]->(:Approval)-[:APPROVES]->(:Decision {id: $d}) "
                         "RETURN count(a)", {"d": r["decision"]}).result_set == [[3]]


def test_v09_stuck_fails_first_step_nothing_to_undo_replan_avoids_it(tenant):
    r = run_execution("s1", "stuck_v09", tenant, 2, reset=True)
    failed = r["failed_status"]
    assert failed["status"] == "failed"
    assert [(t["valve"], t["status"], t["failure"]) for t in failed["tasks"]] == [
        ("V-09", "failed", "stuck"), ("V-01", "cancelled", None), ("V-07", "cancelled", None)]
    assert r["plant_moves"] == []  # nothing moved
    assert r["final"]["status"] == "rolled_back" and r["final"]["actions"] == []
    assert ("rolling_back", "rolled_back") in _transitions(r["audit"])
    assert any(e["reason"] == "nothing_to_undo" for e in r["audit"])
    # the field report became a fact, and the new plan cannot use V-09
    g = TenantGraph(tenant)
    fact = g._g.ro_query("MATCH (f:Fact {kind: 'stuck', status: 'active'})-[:ABOUT]->(:Valve {id: 'V-09'}) "
                         "MATCH (f)-[:EVIDENCED_BY]->(t:Task) RETURN f.id, f.source, t.failure").result_set
    assert len(fact) == 1 and fact[0][1:] == ["field", "stuck"]
    rp = r["replan"]
    assert rp["kind"] == "escalate" and rp["chosen"] is None
    rescue = next(p for p in rp["plans"] if p["label"] == "close V-01 + V-07, open V-09")
    feas = next(c for c in rescue["checks"] if c["code"] == "feasible")
    assert feas["detail"]["stuck"] == [{"valve": "V-09", "facts": [fact[0][0]]}]
    assert g._g.ro_query("MATCH (:Decision {id: $n})-[:SUPERSEDES]->(:Decision {id: $o}) RETURN count(*)",
                         {"n": rp["decision_id"], "o": r["first_decision"]}).result_set == [[1]]
    assert _all_legal(r["audit"])


def test_v07_stuck_mid_plan_undo_restores_the_exact_prior_state(tenant, dc):
    before = rows(dc.read("valves_and_caps"))[0]  # the pack as imported: what the plan started from
    r = run_execution("s1", "stuck_v07", tenant, 3, reset=True)
    failed = r["failed_status"]
    assert [(t["valve"], t["status"]) for t in failed["tasks"]] == [("V-09", "done"), ("V-01", "done"), ("V-07", "failed")]
    assert [(a["valve"], a["to_state"]) for a in failed["actions"]] == [("V-09", "open"), ("V-01", "closed")]  # applied
    f = r["final"]
    assert f["status"] == "rolled_back"
    assert [(t["phase"], t["seq"], t["target"], t["valve"], t["status"]) for t in f["tasks"] if t["phase"] == "rollback"] == [
        ("rollback", 1, "open", "V-01", "done"), ("rollback", 2, "closed", "V-09", "done")]  # newest first
    after = rows(TenantGraph(tenant).read("valves_and_caps"))[0]
    assert sorted(after["valves"]) == sorted(before["valves"])
    assert sorted(after["edges"]) == sorted(before["edges"])  # every link capacity back to its exact value
    assert r["plant_valves"]["V-01"] == "open" and r["plant_valves"]["V-09"] == "closed"
    assert [a["phase"] for a in f["actions"]] == ["forward", "forward", "rollback", "rollback"]
    assert r["replan"]["kind"] == "escalate"  # V-07 now recorded stuck
    assert _all_legal(r["audit"])


def test_worker_dies_lease_expires_second_worker_finishes_without_a_double_move(tenant):
    r = run_execution("s1", "worker_dies", tenant, 4, reset=True)
    f = r["final"]
    assert f["status"] == "verified"
    first = f["tasks"][0]
    assert first["attempts"] == 2 and first["owner"] == "tech2"
    assert [(e["actor"], e["to_status"]) for e in r["audit"] if e["subject"] == first["id"]] == [
        ("tech1", "claimed"), ("system", "open"), ("tech2", "claimed"), ("tech2", "done")]
    assert len(r["plant_moves"]) == 3  # the replayed command did not move V-09 again
    assert len(f["actions"]) == 3


def test_graph_change_after_approval_is_refused_and_replanned(tenant):
    r = run_execution("s1", "graph_changes", tenant, 5, reset=True)
    refused = r["refusals"][0]
    assert refused["error"] == "stale_decision"
    assert any(c.startswith("meter FM-A-IN") for c in refused["changes"]), refused["changes"]
    old, new = r["decisions"]
    assert refused["new_decision"] == new and new != old
    g = TenantGraph(tenant)
    assert g._g.ro_query("MATCH (d:Decision {id: $d}) RETURN d.status", {"d": old}).result_set == [["superseded"]]
    assert g._g.ro_query("MATCH (a:Action)-[:IMPLEMENTS]->(:Decision {id: $d}) RETURN count(a)", {"d": old}).result_set == [[0]]
    assert r["final"]["decision"] == new and r["final"]["status"] == "verified"


def test_expired_approval_goes_back_to_proposed(tenant):
    r = run_execution("s1", "approval_expires", tenant, 1, reset=True)
    assert r["refusals"][0]["error"] == "approval_expired"
    assert r["status_after_expiry"] == "proposed"
    assert _transitions(r["audit"])[:3] == [("proposed", "approved"), ("approved", "proposed"), ("proposed", "approved")]
    assert r["audit"][1]["reason"] == "approval_expired"
    assert r["final"]["status"] == "verified"


def test_s5_is_handled_automatically_and_verified(tenant):
    r = run_execution("s5", "auto", tenant, 2, reset=True)
    f = r["final"]
    assert f["authority_level"] == "L2" and f["status"] == "verified"
    assert r["auto_execution"]["status"] == "executing"  # started inside the investigate call
    assert [e["actor"] for e in r["audit"] if e["kind"] == "decision"] == ["auto", "auto", "tech1", "checker"]
    assert f["approval"]["by"] == "auto"
    assert {a["authorized_by"] for a in f["actions"]} == {"POL-DC-1"}  # the policy, not a person
    iso = next(c for c in f["verification"]["checks"] if c["code"] == "leak_isolated")
    assert iso["detail"]["method"] == "balance"  # SEG-A3 has no inflow meter


def test_s5_passing_valve_fails_verification_and_is_undone_automatically(tenant):
    r = run_execution("s5", "passing_valve", tenant, 3, reset=True)
    f = r["final"]
    assert f["status"] == "rolled_back"
    assert f["verification"]["passed"] is False
    assert set(f["verification"]["failed_checks"]) == {"leak_isolated", "balance_restored"}
    assert ("failed", "rolling_back") in _transitions(r["audit"])
    undo = next(e for e in r["audit"] if e["to_status"] == "rolling_back")
    assert undo["actor"] == "auto" and undo["reason"].startswith("auto_rollback")
    assert [m["target"] for m in r["plant_moves"]] == ["closed", "open"]
