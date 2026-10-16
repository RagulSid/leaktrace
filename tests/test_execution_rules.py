"""Rules around carrying out a decision, through the REST API (and the CLI): who may approve, which
transitions are refused, idempotent reports, lost leases, the stale-decision guard, auto-mode pause."""

import json
import time

import pytest

from app import cli
from app.api import auth
from app.cli import bootstrap
from app.execution import service as execution
from app.graph.client import TenantGraph
from scenario_generator.plant import Plant
from scenario_generator.run import PACK, Session, run
from tests.conftest import DATACENTER_PACK, fresh_tenant

PASSWORD = "practice-only-password"


@pytest.fixture
def s1():
    """A fresh tenant with the S1 decision committed (L3, proposed, requested by operator1)."""
    tenant = fresh_tenant()
    out = run("s1", tenant, seed=4, reset=True, password=PASSWORD)
    sess = Session(tenant, PASSWORD)
    yield sess, out["decision"]["decision_id"], out
    TenantGraph(tenant).delete()


@pytest.fixture
def other_tenant():
    t = fresh_tenant()
    bootstrap(t, password=PASSWORD)
    sess = Session(t, PASSWORD)
    sess.post("/assets/import", "manager1", json.loads(DATACENTER_PACK.read_text(encoding="utf-8")))
    yield sess
    TenantGraph(t).delete()


def _plant(seed=4, **kw):
    return Plant(json.loads(PACK.read_text(encoding="utf-8")), seed=seed, leak_segment="SEG-A1", leak_flow=10.0, **kw)


def test_requester_cannot_approve_their_own_decision(s1):
    sess, did, out = s1
    assert out["decision"]["requested_by"] == "operator1"
    r = sess.post(f"/decisions/{did}/approve", "operator1", expect=403)
    assert r["error"] == "self_approval"
    assert sess.get(f"/decisions/{did}/status", "operator1")["status"] == "proposed"
    sess.post(f"/decisions/{did}/approve", "manager1")  # someone else may


@pytest.mark.parametrize("user", ["staff1", "tech1", "meters1", "safety1"])
def test_wrong_roles_cannot_approve_or_execute(s1, user):
    sess, did, _ = s1
    assert sess.post(f"/decisions/{did}/approve", user, expect=403)
    assert sess.post(f"/decisions/{did}/execute", user, expect=403)
    assert sess.post(f"/decisions/{did}/rollback", user, expect=403)
    assert sess.get(f"/decisions/{did}/status", "operator1")["status"] == "proposed"


def test_only_field_crew_pick_up_valve_moves(s1):
    sess, did, _ = s1
    sess.post(f"/decisions/{did}/approve", "operator2")
    sess.post(f"/decisions/{did}/execute", "operator1")
    for user in ("operator1", "manager1", "meters1", "staff1"):
        sess.post("/tasks/claim", user, {}, expect=403)
    assert sess.post("/tasks/claim", "tech1", {})["task"]["valve"] == "V-09"


def test_another_customer_cannot_touch_the_decision(s1, other_tenant):
    sess, did, _ = s1
    b = other_tenant
    for path in ("approve", "reject", "execute", "verify", "rollback", "replan"):
        assert b.post(f"/decisions/{did}/{path}", "operator2", expect=404)["error"] == "no_such_decision"
    assert b.get(f"/decisions/{did}/status", "operator1", expect=404)
    assert b.get(f"/decisions/{did}/audit", "operator1", expect=404)
    sess.post(f"/decisions/{did}/approve", "operator2")
    sess.post(f"/decisions/{did}/execute", "operator1")
    assert b.post("/tasks/claim", "tech1", {})["task"] is None  # A's open step is invisible to B
    t = sess.get(f"/decisions/{did}/status", "operator1")["tasks"][0]
    assert b.post(f"/tasks/{t['id']}/result", "tech1", {"idempotency_key": "x", "outcome": "done",
                                                        "observed_state": "open"}, expect=404)
    assert sess.post("/tasks/claim", "tech1", {})["task"]["id"] == t["id"]


def test_forged_and_expired_tokens_are_refused(s1, other_tenant):
    sess, did, _ = s1
    c = sess.c
    tok = other_tenant.headers("operator2")["Authorization"].split()[1]
    claims, sig = tok.split(".")
    forged = auth._b64(json.dumps({**json.loads(auth._unb64(claims)), "tenant": sess.tenant}, sort_keys=True).encode())
    expired, _ = auth.issue_token("operator2", "operator", sess.tenant, ttl_s=-1)
    for bad in (f"{forged}.{sig}", expired, "nonsense"):
        h = {"Authorization": f"Bearer {bad}"}
        assert c.post(f"/decisions/{did}/approve", headers=h).status_code == 401
        assert c.post(f"/decisions/{did}/execute", headers=h).status_code == 401
        assert c.post("/tasks/claim", headers=h, json={}).status_code == 401
    assert c.post(f"/decisions/{did}/approve").status_code == 401
    assert sess.get(f"/decisions/{did}/status", "operator1")["status"] == "proposed"


def test_illegal_transitions_are_refused(s1):
    sess, did, _ = s1
    assert sess.post(f"/decisions/{did}/execute", "operator1", expect=409)["error"] == "needs_approval"
    for path in ("verify", "rollback", "replan"):
        r = sess.post(f"/decisions/{did}/{path}", "operator1", expect=409)
        assert r["error"] == "illegal_transition" and r["status"] == "proposed"
    sess.post(f"/decisions/{did}/approve", "operator2")
    assert sess.post(f"/decisions/{did}/approve", "manager1", expect=409)["error"] == "illegal_transition"
    sess.post(f"/decisions/{did}/reject", "manager1", {"reason": "changed my mind"})
    for path, user in (("approve", "operator2"), ("execute", "operator1"), ("reject", "manager1")):
        r = sess.post(f"/decisions/{did}/{path}", user, expect=409)
        assert r["status"] == "rejected"
    st = sess.get(f"/decisions/{did}/status", "operator1")
    assert st["status"] == "rejected" and st["approval"] is None and st["actions"] == []
    audit = sess.get(f"/decisions/{did}/audit", "operator1")
    assert [(e["from_status"], e["to_status"], e["actor"], e["role"]) for e in audit] == [
        ("proposed", "approved", "operator2", "operator"), ("approved", "rejected", "manager1", "manager")]
    assert audit[1]["reason"] == "changed my mind" and all(e["ts"] for e in audit)


def test_approval_ttl_is_bounded(s1):
    sess, did, _ = s1
    assert sess.post(f"/decisions/{did}/approve", "operator2", {"ttl_s": 10 ** 6}, expect=422)["error"] == "bad_ttl"
    assert sess.post(f"/decisions/{did}/approve", "operator2", {"ttl_s": 0}, expect=422)


def test_a_repeated_report_does_not_move_twice(s1):
    sess, did, _ = s1
    sess.post(f"/decisions/{did}/approve", "operator2")
    sess.post(f"/decisions/{did}/execute", "operator1")
    plant = _plant()
    t = sess.post("/tasks/claim", "tech1", {})["task"]
    res = plant.command(t["idempotency_key"], t["valve"], t["target"])
    body = {"idempotency_key": t["idempotency_key"], "outcome": "done", "observed_state": res["observed"]}
    first = sess.post(f"/tasks/{t['id']}/result", "tech1", body)
    again = sess.post(f"/tasks/{t['id']}/result", "tech1", body)  # e.g. the phone retried after a timeout
    assert first["duplicate"] is False and again["duplicate"] is True
    assert plant.command(t["idempotency_key"], t["valve"], t["target"])["replayed"] is True
    assert len(plant.moves) == 1
    st = sess.get(f"/decisions/{did}/status", "operator1")
    assert [(a["valve"], a["to_state"]) for a in st["actions"]] == [("V-09", "open")]
    assert [(x["seq"], x["status"]) for x in st["tasks"]] == [(1, "done"), (2, "open"), (3, "pending")]
    dones = [e for e in sess.get(f"/decisions/{did}/audit", "operator1") if e["subject"] == t["id"] and e["to_status"] == "done"]
    assert len(dones) == 1
    wrong = sess.post(f"/tasks/{t['id']}/result", "tech1", {**body, "idempotency_key": "guess"}, expect=409)
    assert wrong["error"] == "wrong_idempotency_key"


def test_a_worker_whose_lease_ran_out_cannot_report(s1):
    sess, did, _ = s1
    sess.post(f"/decisions/{did}/approve", "operator2")
    sess.post(f"/decisions/{did}/execute", "operator1")
    t = sess.post("/tasks/claim", "tech1", {"lease_s": 1})["task"]
    time.sleep(1.3)
    t2 = sess.post("/tasks/claim", "tech2", {"lease_s": 30})["task"]
    assert t2["id"] == t["id"] and t2["attempts"] == 2
    body = {"idempotency_key": t["idempotency_key"], "outcome": "done", "observed_state": "open"}
    assert sess.post(f"/tasks/{t['id']}/result", "tech1", body, expect=409)["error"] == "lease_lost"
    assert sess.post(f"/tasks/{t['id']}/result", "tech2", body)["duplicate"] is False


def test_worker_lost_three_times_fails_the_execution(s1):
    sess, did, _ = s1
    sess.post(f"/decisions/{did}/approve", "operator2")
    sess.post(f"/decisions/{did}/execute", "operator1")
    for _ in range(3):
        assert sess.post("/tasks/claim", "tech1", {"lease_s": 1})["task"]["seq"] == 1
        time.sleep(1.2)
    st = sess.get(f"/decisions/{did}/status", "operator1")
    assert st["status"] == "failed"
    assert [x["status"] for x in st["tasks"]] == ["abandoned", "cancelled", "cancelled"]
    # an abandoned step may or may not have moved: undo commands it back to its prior state anyway
    rb = sess.post(f"/decisions/{did}/rollback", "operator1")
    assert [(x["phase"], x["target"], x["valve"]) for x in rb["tasks"] if x["phase"] == "rollback"] == [
        ("rollback", "closed", "V-09")]


@pytest.mark.parametrize("change,expect", [
    ("MATCH (v:Valve {id:'V-09'}) CREATE (:Fact {id:'F-T1', kind:'stuck', status:'active', statement:'seized', "
     "source:'synthetic'})-[:ABOUT]->(v)", "fact F-T1"),
    ("MATCH (v:Valve {id:'V-04'}) SET v.state = 'closed'", "valve V-04"),
    ("MATCH (c:Consumer {id:'RACK-A2'}) SET c.criticality = 5", "consumer RACK-A2"),
])
def test_stale_decision_is_refused_and_reinvestigated(s1, change, expect):
    sess, did, _ = s1
    sess.post(f"/decisions/{did}/approve", "operator2")
    TenantGraph(sess.tenant)._g.query(change)  # the world changes after the approval
    r = sess.post(f"/decisions/{did}/execute", "operator1", expect=409)
    assert r["error"] == "stale_decision" and any(c.startswith(expect) for c in r["changes"]), r["changes"]
    st = sess.get(f"/decisions/{did}/status", "operator1")
    assert st["status"] == "superseded" and st["actions"] == [] and st["tasks"] == []
    new = sess.get(f"/decisions/{r['new_decision']}/status", "operator1")
    assert new["requested_by"] == "operator1" and new["status"] in ("proposed", "recorded")
    if expect.startswith("fact"):
        assert r["new_kind"] == "escalate"  # the new plan cannot use V-09
    assert TenantGraph(sess.tenant)._g.ro_query("MATCH (t:Task {kind:'valve_move'}) RETURN count(t)").result_set == [[0]]


def test_meter_noise_is_not_a_material_change(s1):
    sess, did, out = s1
    sess.post(f"/decisions/{did}/approve", "operator2")
    sess.post("/readings", "meters1", {"readings": [{"id": "FM-RA1", "ts": 1.0, "value": 21.0}]})  # within tolerance
    assert sess.post(f"/decisions/{did}/execute", "operator1")["status"] == "executing"


def test_l4_is_never_executed(s1):
    sess, did, _ = s1
    TenantGraph(sess.tenant)._g.query("MATCH (d:Decision {id:$d}) SET d.authority_level = 'L4'", {"d": did})
    assert sess.post(f"/decisions/{did}/approve", "operator2", expect=409)["error"] == "people_decide"
    assert sess.post(f"/decisions/{did}/execute", "operator1", expect=409)["error"] == "people_decide"
    assert sess.get(f"/decisions/{did}/status", "operator1")["next"] == []


def test_paused_auto_mode_turns_l2_into_l3_at_execute_time():
    tenant = fresh_tenant()
    try:
        out = run("s5", tenant, seed=2, reset=True, password=PASSWORD, investigate=False)
        tg = TenantGraph(tenant)
        rec = execution.investigate(tg, out["incident"], "operator1", "operator", auto=False)
        assert rec["authority"]["level"] == "L2"
        tg._g.query("MATCH (p:AuthorityPolicy {id:'POL-DC-1'}) SET p.frozen = true")  # manager pauses auto mode
        sess = Session(tenant, PASSWORD)
        did = rec["decision_id"]
        r = sess.post(f"/decisions/{did}/execute", "operator1", expect=409)
        assert r == {"error": "needs_approval", "authority_level": "L3", "reason": "auto_mode_paused"}
        st = sess.get(f"/decisions/{did}/status", "operator1")
        assert st["authority_level"] == "L3" and "policy_active" in st["failed_conditions"]
        assert st["status"] == "proposed" and st["next"] == ["approve", "reject"]
        a = sess.get(f"/decisions/{did}/audit", "operator1")
        assert [(e["kind"], e["from_status"], e["to_status"], e["reason"]) for e in a] == [
            ("authority", "L2", "L3", "auto_mode_paused")]
        sess.post(f"/decisions/{did}/approve", "operator2")  # now a person must say OK
        assert sess.post(f"/decisions/{did}/execute", "operator1")["status"] == "executing"
    finally:
        TenantGraph(tenant).delete()


def test_investigating_again_while_executing_is_refused(s1):
    sess, did, out = s1
    sess.post(f"/decisions/{did}/approve", "operator2")
    sess.post(f"/decisions/{did}/execute", "operator1")
    r = sess.post(f"/incidents/{out['incident']}/investigate", "operator1", expect=409)
    assert r["error"] == "execution_in_progress" and r["decision"] == did


def test_a_new_investigation_supersedes_an_open_decision(s1):
    sess, did, out = s1
    sess.post(f"/decisions/{did}/approve", "operator2")
    new = sess.post(f"/incidents/{out['incident']}/investigate", "manager1")
    assert sess.get(f"/decisions/{did}/status", "operator1")["status"] == "superseded"
    assert sess.get(f"/decisions/{new['decision_id']}/status", "operator1")["status"] == "proposed"
    assert sess.post(f"/decisions/{did}/execute", "operator1", expect=409)["status"] == "superseded"


def test_cli_follows_the_same_rules(s1, capsys):
    sess, did, _ = s1
    t = sess.tenant
    assert cli.main(["approve", "--tenant", t, "--as", "operator1", "--decision", did]) == 3
    assert json.loads(capsys.readouterr().err)["error"] == "self_approval"
    assert cli.main(["approve", "--tenant", t, "--as", "staff1", "--decision", did]) == 3
    assert json.loads(capsys.readouterr().err)["error"] == "role_not_allowed"
    assert cli.main(["approve", "--tenant", t, "--as", "nobody", "--decision", did]) == 3
    assert json.loads(capsys.readouterr().err)["error"] == "unknown_user"
    assert cli.main(["approve", "--tenant", t, "--as", "operator2", "--decision", did, "--note", "cli"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "approved"
    assert cli.main(["execute", "--tenant", t, "--as", "operator1", "--decision", did]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "executing"
    assert cli.main(["status", "--tenant", t, "--as", "operator1", "--decision", did]) == 0
    assert [x["valve"] for x in json.loads(capsys.readouterr().out)["tasks"]] == ["V-09", "V-01", "V-07"]
    assert cli.main(["audit", "--tenant", t, "--as", "operator1", "--decision", did]) == 0
    assert [e["actor"] for e in json.loads(capsys.readouterr().out)] == ["operator2", "operator1"]
    assert cli.main(["status", "--tenant", t, "--as", "tech1", "--decision", did]) == 3  # crew cannot read decisions
    assert json.loads(capsys.readouterr().err)["error"] == "role_not_allowed"
    assert cli.main(["verify", "--tenant", t, "--as", "operator1", "--decision", did]) == 3
    assert json.loads(capsys.readouterr().err)["status"] == "executing"
    # the other customer's graph does not have this decision
    other = fresh_tenant()
    try:
        bootstrap(other, password=PASSWORD)
        assert cli.main(["status", "--tenant", other, "--as", "operator1", "--decision", did]) == 3
        assert json.loads(capsys.readouterr().err)["error"] == "no_such_decision"
    finally:
        TenantGraph(other).delete()
