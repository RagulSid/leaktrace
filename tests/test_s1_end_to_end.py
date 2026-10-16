"""Scenario S1 end to end through the REST API, across seeds, checked against hand-worked answers.

Hand-worked for the data-centre pack (leak on SEG-A1; racks A1 and B1 critical, need 20 each):
  plan                          failed checks
  close V-01 + V-07, open V-09  none  -> chosen. Row B feeds both rows through the backup link:
                                        A1 20, B1 20 alone and together; all four racks together 50 of 70,
                                        so the 20 short goes to the least critical racks: B2 15, A2 5;
                                        disruption = 1*15/15 + 2*5/15 = 1.667
  do nothing                    leak_isolated, energised_exposure
  close V-01 + open V-09        leak_isolated (backfeed through V-07: 40), energised_exposure
  close V-07 + open V-09        leak_isolated, energised_exposure
  close V-01                    critical_supplied, critical_joint, workloads_handled (A1 gets 0)
  close V-01 + V-07             critical_supplied, critical_joint, workloads_handled
  close V-07                    leak_isolated, critical_supplied, critical_joint, energised_exposure, workloads_handled
Authority: L3, because rack A1 (criticality 5) is affected and the policy ceiling is 3, and the plan needs 3
valve moves where the policy allows 2. Confidence: alarm 0.35 + pressure 0.20 + imbalance 0.25 + report 0.10.
"""

import pytest

from app.graph.client import TenantGraph, rows
from scenario_generator.run import run as run_scenario
from tests.conftest import fresh_tenant

EXPECTED_FAILED = {
    "close V-01 + V-07, open V-09": [],
    "do nothing": ["leak_isolated", "energised_exposure"],
    "close V-01, open V-09": ["leak_isolated", "energised_exposure"],
    "close V-07, open V-09": ["leak_isolated", "energised_exposure"],
    "close V-01": ["critical_supplied", "critical_joint", "workloads_handled"],
    "close V-01 + V-07": ["critical_supplied", "critical_joint", "workloads_handled"],
    "close V-07": ["leak_isolated", "critical_supplied", "critical_joint", "energised_exposure", "workloads_handled"],
}


@pytest.fixture(scope="module", params=[1, 2, 3])
def s1(request):
    tenant = fresh_tenant()
    out = run_scenario("s1", tenant, seed=request.param, reset=True)
    yield out, TenantGraph(tenant)
    TenantGraph(tenant).delete()


def test_decision_and_authority(s1):
    out, _ = s1
    d = out["decision"]
    assert d["kind"] == "act"
    assert d["suspect"]["segment"] == "SEG-A1"
    assert d["suspect"]["confidence"]["score"] == 0.9
    assert d["suspect"]["confidence"]["signs_agree"] == 4
    assert d["authority"]["level"] == "L3"
    assert d["authority"]["failed"] == [
        {"code": "criticality_ceiling", "value": 5, "allowed": 3},
        {"code": "operation_limit", "value": 3, "allowed": 2},
    ]
    chosen = d["plans"][0]
    assert chosen["id"] == d["chosen"] and chosen["label"] == "close V-01 + V-07, open V-09"
    assert d["fallback"] is None  # no second plan passes every check


def test_every_plan_and_its_failed_checks(s1):
    out, _ = s1
    plans = out["decision"]["plans"]
    assert {p["label"]: p["failed_checks"] for p in plans} == EXPECTED_FAILED
    assert [p["label"] for p in plans][:2] == ["close V-01 + V-07, open V-09", "do nothing"]


def test_flow_numbers_come_from_max_flow(s1):
    out, _ = s1
    plans = {p["label"]: p for p in out["decision"]["plans"]}
    ch = {c["code"]: c["detail"] for c in plans["close V-01 + V-07, open V-09"]["checks"]}
    assert ch["leak_isolated"] == {"flow_into_leak": 0.0}
    assert ch["critical_supplied"]["consumers"] == {"RACK-A1": {"flow": 20.0, "required": 20},
                                                    "RACK-B1": {"flow": 20.0, "required": 20}}
    assert ch["critical_joint"] == {"flow": 40.0, "required": 40}
    chosen = plans["close V-01 + V-07, open V-09"]
    assert chosen["shortfall"] == {"RACK-A1": 0.0, "RACK-A2": 5.0, "RACK-B1": 0.0, "RACK-B2": 15.0}
    assert chosen["disruption"] == 1.667
    assert chosen["steps"] == ["inspect:Z-A", "migrate:WL-BATCH-12", "migrate:WL-DEV-01"]
    assert chosen["rollback"] == ["open:V-01", "open:V-07", "close:V-09"]
    backfeed = {c["code"]: c["detail"] for c in plans["close V-01, open V-09"]["checks"]}
    assert backfeed["leak_isolated"] == {"flow_into_leak": 40.0}
    nearest = {c["code"]: c["detail"] for c in plans["close V-01"]["checks"]}
    assert nearest["critical_supplied"]["consumers"]["RACK-A1"]["flow"] == 0.0
    assert nearest["workloads_handled"] == {"cannot_move": ["WL-TRAIN-07"]}


def test_evidence_is_read_from_the_graph(s1):
    out, _ = s1
    d = out["decision"]
    sig = d["suspect"]["signals"]
    assert sig["leak_alarms"] == ["LS-A1"] and sig["pressure_anomalies"] == ["PS-MA"]
    bal = d["suspect"]["balance"]
    assert bal["meter"] == "FM-A-IN" and bal["out_meters"] == ["FM-RA1", "FM-RA2"]
    assert abs(bal["unaccounted"] - out["leak_flow"]) < 1.3  # seeded leak, meter noise within +-0.4 each
    assert "LS-A1 -> SEG-A1 -> V-07 -> J-MA -> V-03 -> SEG-A2 -> RACK-A1" in d["evidence_paths"]
    owners = {x["consumer"]: x["owners"] for x in d["impact"]["downstream"]}
    assert owners == {"RACK-A1": ["T-ML"], "RACK-A2": ["T-DATA"]}


def test_decision_is_stored_in_the_graph(s1):
    out, tg = s1
    did, chosen = out["decision"]["decision_id"], out["decision"]["chosen"]
    g = tg._g
    assert g.ro_query("MATCH (:Incident {id:$i})-[:DECIDED]->(d:Decision {id:$d}) RETURN d.authority_level, d.failed_conditions",
                      {"i": out["incident"], "d": did}).result_set == [["L3", ["criticality_ceiling", "operation_limit"]]]
    assert g.ro_query("MATCH (:Decision {id:$d})-[:CHOSE {role:'chosen'}]->(o:Option)-[:OPERATES]->(v:Valve) "
                      "RETURN o.id, collect(v.id)", {"d": did}).result_set[0][0] == chosen
    assert sorted(g.ro_query("MATCH (:Decision {id:$d})-[:CHOSE {role:'chosen'}]->(:Option)-[:OPERATES]->(v) RETURN v.id",
                             {"d": did}).result_set) == [["V-01"], ["V-07"], ["V-09"]]
    assert g.ro_query("MATCH (:Incident {id:$i})-[:HAS_OPTION]->(o:Option) RETURN count(o)",
                      {"i": out["incident"]}).result_set == [[7]]
    just = {r[0] for r in g.ro_query("MATCH (:Decision {id:$d})-[:JUSTIFIED_BY]->(e) RETURN e.id", {"d": did}).result_set}
    assert {"LS-A1", "PS-MA", "FM-A-IN", "FM-RA1", "FM-RA2", "POL-DC-1", "RACK-A1", "RACK-A2"} <= just
    assert any(j.startswith("REP-") for j in just)
    # reading it back through the API gives the same record
    rec = out["decision"]
    assert rows(tg.read("decision_get", {"id": did}))[0]["decision"]["summary"] == rec["summary"]


def test_tool_calls_are_episodes_and_nothing_was_executed(s1):
    out, tg = s1
    eps = rows(tg.read("episodes_for_incident", {"incident": out["incident"]}))
    assert [e["tool"] for e in eps] == out["decision"]["tool_sequence"]
    assert all(e["ok"] for e in eps)
    g = tg._g
    leftovers = g.ro_query("MATCH ()-[r:FLOWS_TO]->() WITH keys(r) AS ks UNWIND ks AS k WITH k "
                           "WHERE k STARTS WITH 'cap_o_' RETURN count(k)").result_set[0][0]
    assert leftovers == 0  # every what-if capacity was removed
    assert g.ro_query("MATCH (a:Action) RETURN count(a)").result_set == [[0]]
    assert g.ro_query("MATCH (v:Valve) WHERE v.state <> v.normal_state RETURN count(v)").result_set == [[0]]
