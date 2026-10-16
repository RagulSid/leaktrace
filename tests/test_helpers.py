"""The six helpers: they choose tools in a loop, hand work on only through Task nodes, and cannot do anything
the code does not allow, whatever the chooser asks for.

These tests use the fixed offline chooser (RuleChooser) so they repeat exactly, and a scripted chooser that
tries things it must not. The model chooser is tested against a fake server in test_model_chooser.py.
"""

import json
import pytest

from app import config
from app.agents import runtime
from app.agents.choosers import RuleChooser, ToolCall
from app.agents.roles import ROLES
from app.graph.client import TenantGraph, rows
from scenario_generator.run import Session, run, run_helpers
from tests.conftest import fresh_tenant

PASSWORD = "practice-only-password"


@pytest.fixture(scope="module")
def helper_runs():
    """S1 (approved by a person), S2 (weak evidence) and S5 (auto), each carried by the helpers."""
    out, tenants = {}, []
    for name, variant in (("s1", "approve"), ("s2", "evidence"), ("s5", "auto")):
        t = fresh_tenant()
        tenants.append(t)
        out[name] = run_helpers(name, variant, t, 2, reset=True, password=PASSWORD)
    yield out
    for t in tenants:
        TenantGraph(t).delete()


def _chain_kinds(r):
    return [c["kind"] for c in r["chain"]]


def test_s1_hand_offs_go_through_task_nodes(helper_runs):
    r = helper_runs["s1"]
    assert _chain_kinds(r) == ["triage", "investigate", "plan", "dispatch", "verify", "record"]
    assert all(c["status"] == "done" for c in r["chain"])
    by_kind = {c["kind"]: c for c in r["chain"]}
    for a, b in [("triage", "investigate"), ("investigate", "plan"), ("plan", "dispatch"), ("dispatch", "verify"),
                 ("verify", "record")]:
        assert by_kind[b]["id"] in by_kind[a]["handed_to"]
    assert by_kind["dispatch"]["attempts"] == 2  # waited for the person's OK, woke when it came
    assert {c["agents"][0] for c in r["chain"]} == {"intake", "investigator", "planner", "dispatcher", "checker",
                                                    "record_keeper"}
    g = TenantGraph(r["investigation"]["tenant"])._g
    assert g.ro_query("MATCH (:Task)-[h:HANDED_OFF_TO]->(:Task)-[:FOR]->(:Incident {id:$i}) RETURN count(h)",
                      {"i": r["incident"]}).result_set == [[5]]
    d = r["final"]
    assert d["status"] == "verified" and d["authority_level"] == "L3" and d["approval"]["by"] == "operator2"
    assert d["plan"]["label"] == "close V-01 + V-07, open V-09"  # same decision as the fixed sequence
    assert r["incident_after"]["status"] == "resolved"
    assert r["report"]["prose_by"] == "template" and d["decision"] in r["report"]["prose"]


def test_each_helper_uses_only_its_own_tools(helper_runs):
    by_role = {role.name: set(role.tools) for role in ROLES.values()}
    for r in helper_runs.values():
        for actor, tools_used in r["steps_by_role"].items():
            assert set(tools_used) <= by_role[actor], (actor, tools_used)
    # nobody can approve, reject, undo or touch the policy: those are for people (or auto mode in code)
    every_tool = {t for ts in by_role.values() for t in ts}
    assert not every_tool & {"approve", "reject", "rollback", "set_policy", "freeze", "execute_any"}


def test_s1_s2_s5_tool_sequences_differ(helper_runs):
    seq = {k: [t for role in ("intake", "investigator", "planner", "dispatcher", "checker", "record_keeper")
               for t in r["steps_by_role"].get(role, [])] for k, r in helper_runs.items()}
    assert len({tuple(v) for v in seq.values()}) == 3
    s2 = helper_runs["s2"]
    assert "ask_for_evidence" in seq["s2"] and "list_plans" not in seq["s2"] and "start_plan" not in seq["s2"]
    assert s2["final"]["kind"] == "request_evidence" and _chain_kinds(s2) == ["triage", "investigate", "dispatch", "record"]
    assert "wait_for_approval" in seq["s1"] and "wait_for_approval" not in seq["s5"]
    s5 = helper_runs["s5"]
    assert s5["final"]["authority_level"] == "L2" and s5["final"]["approval"]["by"] == "auto"
    assert s5["final"]["status"] == "verified"


def test_every_helper_step_is_an_episode_with_its_chooser(helper_runs):
    r = helper_runs["s1"]
    g = TenantGraph(r["investigation"]["tenant"])._g
    eps = g.ro_query("MATCH (e:Episode {kind:'agent_step'})-[:OF]->(:Incident {id:$i}) RETURN e.args_json",
                     {"i": r["incident"]}).result_set
    assert len(eps) == sum(len(v) for v in r["steps_by_role"].values())
    assert {json.loads(a[0])["chooser"] for a in eps} == {"rules"}


# ---------------------------------------------------------------- authority stays in code


class Scripted:
    """A chooser that plays a fixed list of calls per role, including things it must not do."""

    name = "scripted"
    prose_writer = None

    def __init__(self, script: dict[str, list[tuple[str, dict]]]):
        self.script = {k: list(v) for k, v in script.items()}

    def choose(self, role, brief, history):
        calls = self.script.get(role.name) or []
        if len(history) >= len(calls):
            return None
        name, args = calls[len(history)]
        return ToolCall(f"s{len(history)}", name, args)


@pytest.fixture
def s1_open():
    """S1 events in, the problem waiting for its Intake step."""
    t = fresh_tenant()
    out = run("s1", t, seed=3, reset=True, password=PASSWORD, investigate=False)
    yield TenantGraph(t), out["incident"]
    TenantGraph(t).delete()


def _results(tg, incident, actor):
    return [(e["tool"], json.loads(e["summary"])) for e in
            rows(tg.read("episodes_for_incident", {"incident": incident})) if e["kind"] == "agent_step" and e["actor"] == actor]


def test_refusals_come_from_code_not_from_the_chooser(s1_open, monkeypatch):
    tg, inc = s1_open
    runtime.drain(tg, RuleChooser(), max_steps=3)  # intake, investigator, planner: a plan waits for approval
    did = rows(tg.read("incident_get", {"id": inc}))[0]["decisions"][0]
    script = Scripted({"dispatcher": [
        ("approve", {}),                     # not one of its tools
        ("start_plan", {}),                  # L3: refused until a person approves
        ("pass_to_checker", {}),             # nothing started
        ("decision_status", {"oops": 1}),    # wrong arguments
        ("wait_for_approval", {}),
    ]})
    done = runtime.drain(tg, script)
    assert [d.status for d in done] == ["waiting"]
    res = _results(tg, inc, "dispatcher")
    assert [(t, r.get("refused")) for t, r in res] == [
        ("approve", "not_your_tool"), ("start_plan", "needs_approval"), ("pass_to_checker", "plan_not_started"),
        ("decision_status", "bad_arguments"), ("wait_for_approval", None)]
    assert tg._g.ro_query("MATCH (d:Decision {id:$d}) RETURN d.status", {"d": did}).result_set == [["proposed"]]
    assert tg._g.ro_query("MATCH (a:Action) RETURN count(a)").result_set == [[0]]


def test_investigator_cannot_pass_weak_evidence_and_planner_cannot_skip_tests(s1_open):
    tg, inc = s1_open
    runtime.drain(tg, RuleChooser(), max_steps=1)  # intake only
    tg._g.query("MATCH (s:Sensor {id:'PS-MA'}) SET s.state = 'OK'")  # weaker evidence than S1 normally has
    tg._g.query("MATCH (m:Meter {id:'FM-A-IN'}) SET m.value = 35.0")   # and the meters balance: a contradiction
    script = Scripted({"investigator": [("look_at_problem", {}), ("find_suspects", {}),
                                        ("check_suspect", {"segment": "SEG-A1"}),
                                        ("trace_impact", {"segment": "SEG-A1"}), ("recall_memory", {}),
                                        ("pass_to_planner", {"segment": "SEG-A1"}), ("ask_for_evidence", {})]})
    runtime.drain(tg, script, max_steps=1)
    res = dict((t, r) for t, r in _results(tg, inc, "investigator"))
    assert res["pass_to_planner"]["refused"] == "not_enough_evidence"
    assert res["ask_for_evidence"]["kind"] == "request_evidence"
    other = fresh_tenant()
    try:
        run("s1", other, seed=3, reset=True, password=PASSWORD, investigate=False)
        g2 = TenantGraph(other)
        runtime.drain(g2, RuleChooser(), max_steps=2)  # intake and investigator: a plan step is open
        inc2 = rows(g2.read("incidents_list"))[0]["id"]
        runtime.drain(g2, Scripted({"planner": [("list_plans", {}), ("commit_decision", {}),
                                                ("test_plan", {"plan_id": "made_up"})]}), max_steps=1)
        res2 = _results(g2, inc2, "planner")
        assert res2[1][1]["refused"] == "untested_plans" and len(res2[1][1]["plans"]) == 7
        assert res2[2][1]["refused"] == "unknown_plan"
        assert rows(g2.read("incident_get", {"id": inc2}))[0]["decisions"] == []
    finally:
        TenantGraph(other).delete()


def test_a_helper_that_never_finishes_hands_the_step_to_people(s1_open, monkeypatch):
    tg, inc = s1_open
    monkeypatch.setattr(config, "AGENT_MAX_STEPS", 4)
    loop = Scripted({"intake": [("look_at_problem", {})] * 10})
    done = runtime.drain(tg, loop, max_steps=1)
    assert done[0].status == "failed" and done[0].handed_to == [] and len(done[0].tools) == 4
    t = tg._g.ro_query("MATCH (t:Task {kind:'triage'}) RETURN t.status, t.result_json").result_set[0]
    assert t[0] == "failed" and json.loads(t[1])["reason"] == "no_finish"


def test_expired_helper_lease_reopens_the_step(s1_open, monkeypatch):
    tg, inc = s1_open
    monkeypatch.setattr(config, "AGENT_LEASE_S", -1)  # the claim is already expired
    claimed = runtime.claim(tg, RuleChooser())
    assert claimed["kind"] == "triage"
    from app.execution import service

    swept = service.sweep(tg)
    assert claimed["id"] in swept["helper_steps_released"]
    assert tg._g.ro_query("MATCH (t:Task {id:$t}) RETURN t.status", {"t": claimed["id"]}).result_set == [["open"]]
