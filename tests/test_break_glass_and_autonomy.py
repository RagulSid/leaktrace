"""Break-glass and earned autonomy (BUILD_PROMPT §5 and §16 test 4).

Break-glass acts on a plan waiting for approval only after the policy's wait, only with a leak alarm and
live equipment near the water, and only if the minimal isolating plan keeps every critical rack supplied,
is reversible and feasible, and confidence is high enough, with auto mode not paused. It refuses otherwise.
Earned autonomy widens the criticality ceiling for a proven playbook, never above the Manager's ceiling, and
the helpers cannot change the policy.
"""

import copy
import json
import time
from dataclasses import replace

import pytest

from app.domain import breakglass
from app.domain.authority import AuthorityInput, compute
from app.graph.client import TenantGraph, rows
from scenario_generator.field import FieldWorker
from scenario_generator.plant import Plant
from scenario_generator.run import PACK, Session, run, run_execution, run_helpers
from tests.conftest import DATACENTER_PACK, fresh_tenant

PASSWORD = "practice-only-password"
POLICY = {"id": "POL-DC-1", "status": "active", "frozen": False, "min_confidence": 0.7, "max_auto_criticality": 3,
          "max_auto_operations": 2, "rate_limit_per_zone_per_hour": 3, "min_playbook_successes": 3,
          "auto_promotion_ceiling": 4, "break_glass_wait_s": 300}


@pytest.fixture
def tenant():
    t = fresh_tenant()
    yield t
    TenantGraph(t).delete()


# ---------------------------------------------------------------- break-glass, pure rules on real records


@pytest.fixture(scope="module")
def records():
    """Committed S1 records from the graph: the normal one and one where V-09 is recorded stuck."""
    out, made = {}, []
    for name, variant in (("s1", None), ("stuck", "stuck_v09")):
        t = fresh_tenant()
        made.append(t)
        if variant:
            r = run_execution("s1", variant, t, 2, reset=True, password=PASSWORD)
            out[name] = Session(t, PASSWORD).get(f"/decisions/{r['replan']['decision_id']}", "operator1")
        else:
            out[name] = run("s1", t, seed=2, reset=True, password=PASSWORD)["decision"]
    yield out
    for t in made:
        TenantGraph(t).delete()


def test_break_glass_would_act_on_s1(records):
    v = breakglass.check(records["s1"], POLICY)
    assert v["execute"] and v["failed"] == [] and v["option"] == records["s1"]["chosen"]
    assert v["trigger"] == {"alarms": ["LS-A1"], "energised_near_water": ["RACK-A1", "RACK-A2"]}


@pytest.mark.parametrize("policy,failed", [
    ({**POLICY, "frozen": True}, ["policy_active"]),
    ({**POLICY, "min_confidence": 0.95}, ["confidence"]),
    (None, ["policy_active", "confidence"]),
])
def test_break_glass_refuses_when_paused_or_unsure(records, policy, failed):
    v = breakglass.check(records["s1"], policy)
    assert not v["execute"] and v["failed"] == failed


def test_break_glass_refuses_when_it_would_starve_a_critical_rack(records):
    v = breakglass.check(records["stuck"], POLICY)
    assert not v["execute"]
    opt = next(p for p in records["stuck"]["plans"] if p["id"] == v["option"])
    assert opt["label"] == "close V-01"  # with V-09 shut, closing V-01 alone stops the leak, and cuts off rack A1
    assert "no_starved_critical" in v["failed"] and "RACK-A1" in opt["starved_critical"]


def test_break_glass_needs_an_alarm_and_live_equipment(records):
    r = copy.deepcopy(records["s1"])
    for e in r["impact"]["exposure"]:
        e["energised"] = False
    assert breakglass.trigger(r) is None
    assert not breakglass.due(POLICY, decided_at=100.0, now=399.0) and breakglass.due(POLICY, 100.0, 400.0)


# ---------------------------------------------------------------- break-glass, live


def _s1_waiting(tenant, wait_s=1, **policy):
    out = run("s1", tenant, seed=5, reset=True, password=PASSWORD)
    sets = ", ".join(f"p.{k} = ${k}" for k in policy)
    TenantGraph(tenant)._g.query(f"MATCH (p:AuthorityPolicy {{id:'POL-DC-1'}}) SET p.break_glass_wait_s = $w"
                                 + (f", {sets}" if sets else ""), {"w": wait_s, **policy})
    return out, Session(tenant, PASSWORD)


def test_break_glass_acts_after_the_wait_and_queues_a_review(tenant):
    out, sess = _s1_waiting(tenant, wait_s=3)
    did = out["decision"]["decision_id"]
    assert sess.get(f"/decisions/{did}/status", "operator1")["status"] == "proposed"  # not yet
    time.sleep(3.2)
    st = sess.get(f"/decisions/{did}/status", "operator1")
    assert st["status"] == "executing" and st["approval"]["by"] == "break_glass"
    reviews = sess.get("/reviews", "manager1")
    assert [(r["kind"], r["status"], r["decision"]) for r in reviews] == [("break_glass", "open", did)]
    trail = [e for e in sess.get(f"/decisions/{did}/audit", "operator1") if e["kind"] == "break_glass"]
    assert trail[0]["to_status"] == "executed" and trail[0]["detail"]["failed"] == []
    tg = TenantGraph(tenant)
    notes = tg._g.ro_query("MATCH (e:Episode {kind:'notify'}) RETURN e.summary").result_set
    assert notes and "Emergency action taken" in notes[0][0]
    plant = Plant(json.loads(PACK.read_text(encoding="utf-8")), seed=5, leak_segment="SEG-A1",
                  leak_flow=out["leak_flow"])
    FieldWorker(sess, "tech1", plant).drain()
    sess.post("/readings", "meters1", {"readings": plant.readings(time.time())})
    st = sess.get(f"/decisions/{did}/status", "operator1")
    assert st["status"] == "verified" and {a["authorized_by"] for a in st["actions"]} == {"POL-DC-1"}


@pytest.mark.parametrize("policy,failed", [({"frozen": True}, "policy_active"), ({"min_confidence": 0.95}, "confidence")])
def test_break_glass_refuses_live_and_escalates(tenant, policy, failed):
    out, sess = _s1_waiting(tenant, wait_s=1, **policy)
    did = out["decision"]["decision_id"]
    time.sleep(1.2)
    st = sess.get(f"/decisions/{did}/status", "operator1")
    assert st["status"] in ("proposed", "superseded") and st["actions"] == [] and st["tasks"] == []
    reviews = sess.get("/reviews", "manager1")
    assert [(r["kind"], r["decision"]) for r in reviews] == [("escalation", did)]
    trail = [e for e in sess.get(f"/decisions/{did}/audit", "operator1") if e["kind"] == "break_glass"]
    assert trail[0]["reason"] == "break_glass_refused" and failed in trail[0]["detail"]["failed"]
    sess.get(f"/decisions/{did}/status", "operator1")  # looked at once only
    assert len(sess.get("/reviews", "manager1")) == 1


def test_break_glass_still_goes_through_the_stale_guard(tenant):
    out, sess = _s1_waiting(tenant, wait_s=1)
    did = out["decision"]["decision_id"]
    TenantGraph(tenant)._g.query("MATCH (v:Valve {id:'V-09'}) CREATE (:Fact {id:'F-BG', kind:'stuck', status:'active', "
                                 "statement:'seized', source:'synthetic'})-[:ABOUT]->(v)")
    time.sleep(1.2)
    st = sess.get(f"/decisions/{did}/status", "operator1")
    assert st["status"] == "superseded" and st["actions"] == []
    trail = [e for e in sess.get(f"/decisions/{did}/audit", "operator1") if e["kind"] == "break_glass"]
    assert trail[0]["detail"]["refused_by"] == "stale_decision"


# ---------------------------------------------------------------- earned autonomy


PB = {"id": "PB-1", "success_count": 3, "failure_count": 0}
BASE = AuthorityInput(policy=POLICY, confidence=0.8, contradictions=0, starved_critical=0, max_affected_criticality=4,
                      reversible_feasible=True, op_count=1, recent_zone_actions=0)


def test_proven_playbook_widens_the_ceiling_up_to_the_managers_limit():
    r = compute(replace(BASE, playbook=PB))
    assert r.level == "L2" and r.widened == {"from": 3, "to": 4, "playbook": "PB-1", "successes": 3, "value": 4}


@pytest.mark.parametrize("case,why", [
    (replace(BASE, playbook=PB, max_affected_criticality=5), "above the Manager's ceiling"),
    (replace(BASE, playbook={**PB, "success_count": 2}), "not enough successes"),
    (replace(BASE, playbook={**PB, "failure_count": 1}), "a failure on record"),
    (replace(BASE, playbook=None), "no playbook"),
    (replace(BASE, playbook=PB, policy={**POLICY, "frozen": True}), "auto mode paused"),
    (replace(BASE, playbook=PB, op_count=3), "other conditions are never widened"),
])
def test_earned_autonomy_never_goes_further(case, why):
    r = compute(case)
    assert r.level == "L3" and r.widened is None, why


def test_helpers_earn_autonomy_on_a_proven_plan_and_cannot_change_the_policy(tenant):
    from app.cli import bootstrap

    bootstrap(tenant, password=PASSWORD, reset=True)
    sess = Session(tenant, PASSWORD)
    sess.post("/assets/import", "manager1", json.loads(DATACENTER_PACK.read_text(encoding="utf-8")))
    g = TenantGraph(tenant)._g
    # a job on rack A2 that matters more (criticality 4, above the auto ceiling of 3); a looser hourly limit
    g.query("MATCH (w:Workload {id:'WL-BATCH-12'}) SET w.criticality = 4")
    g.query("MATCH (p:AuthorityPolicy {id:'POL-DC-1'}) SET p.rate_limit_per_zone_per_hour = 20")
    policy_before = g.ro_query("MATCH (p:AuthorityPolicy) RETURN properties(p)").result_set
    levels = []
    for cycle in range(4):
        r = run_helpers("s5", "auto", tenant, 10 + cycle, password=PASSWORD)
        levels.append((r["final"]["authority_level"], r["final"]["approval"]["by"], r["final"]["status"]))
        # the pipe is repaired and V-04 reopened outside the system before the next leak
        g.query("MATCH (v:Valve {id:'V-04'}) SET v.state = 'open' WITH v "
                "MATCH ()-[e:FLOWS_TO {valve_id:'V-04'}]->() SET e.cap_base = e.open_cap")
    assert levels[:3] == [("L3", "operator2", "verified")] * 3  # a person approves the first three
    assert levels[3] == ("L2", "auto", "verified")  # then the proven playbook runs on its own
    pb = g.ro_query("MATCH (p:Playbook) RETURN p.key, p.success_count, p.failure_count").result_set
    assert pb == [["SEG-A3|close:V-04", 4, 0]]
    widened = g.ro_query("MATCH (a:AuditEvent {kind:'autonomy'}) RETURN a.reason, a.detail_json").result_set
    assert len(widened) == 1 and widened[0][0] == "autonomy_widened"
    assert json.loads(widened[0][1]) == {"from": 3, "to": 4, "playbook": json.loads(widened[0][1])["playbook"],
                                         "successes": 3, "value": 4}
    assert g.ro_query("MATCH (p:AuthorityPolicy) RETURN properties(p)").result_set == policy_before
