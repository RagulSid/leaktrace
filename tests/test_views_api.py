"""The routes behind the screens: public report tracking (demo customer, no internal ids), the problem views,
auto-mode settings (manager only, bounded, audited), learning, field crew steps, and the recorded chooser."""

import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.api import views
from app.api.main import app
from app.graph.client import TenantGraph
from scenario_generator.run import Session, run, run_helpers
from tests.conftest import fresh_tenant

PASSWORD = "practice-only-password"


@pytest.fixture
def helped(monkeypatch):
    """S1 carried by the helpers up to "needs your OK", as the demo customer."""
    t = fresh_tenant()
    out = run_helpers("s1", "approve", t, 2, reset=True, password=PASSWORD)
    monkeypatch.setattr(config, "DEMO_TENANT", t)
    monkeypatch.setattr(views, "public_limit", views.RateLimit(1000))
    yield out, Session(t, PASSWORD), TestClient(app)
    TenantGraph(t).delete()


def test_public_report_and_tracking_show_no_internal_ids(helped):
    out, sess, c = helped
    r = c.post("/public/reports", json={"kinds": ["water", "flooding"], "where": "near Rack B1 in Row B", "severity": "spreading"})
    assert r.status_code == 200 and set(r.json()) == {"code"}
    code = r.json()["code"]
    st = c.get(f"/public/reports/{code}")
    body = json.dumps(st.json())
    assert st.status_code == 200 and "INC-" not in body and "REP-" not in body and "DEC-" not in body
    assert [s["key"] for s in st.json()["stages"]] == ["received", "located", "checked", "crew", "fixed"]
    assert st.json()["stages"][1]["done"] is True  # "Rack B1" and "Row B" were matched on the map
    assert c.post("/public/reports", json={"kinds": ["lava"], "where": "here"}).status_code == 422
    assert c.post("/public/reports", json={"kinds": ["water"], "where": "x", "asset_code": "NOPE"}).status_code == 422
    assert c.get("/public/reports/R-NOTREAL").status_code == 404


def test_i_see_this_too_adds_a_report_to_an_open_problem(helped, monkeypatch):
    out, sess, c = helped
    first = c.post("/public/reports", json={"kinds": ["water"], "where": "under Rack B2 in Row B"}).json()["code"]
    before = c.get(f"/public/reports/{first}").json()["others"]
    again = c.post(f"/public/reports/{first}/confirm")
    assert again.status_code == 200 and again.json()["code"] != first
    assert c.get(f"/public/reports/{first}").json()["others"] == before + 1


def test_problem_view_map_and_timeline(helped):
    out, sess, c = helped
    inc = out["incident"]
    queue = sess.get("/problems", "operator1")
    assert queue[0]["id"] == inc and queue[0]["authority_level"] == "L3" and queue[0]["kind"] == "act"
    p = sess.get(f"/problems/{inc}", "operator1")
    assert p["decision"]["chosen"] and p["status"]["status"] == "verified"
    m = sess.get(f"/problems/{inc}/map", "operator1")
    assert m["highlight"]["suspect"] == "SEG-A1" and "RACK-A1" in m["highlight"]["path"]
    assert sorted(m["highlight"]["plan_valves"]) == ["V-01", "V-07", "V-09"]
    assert {n["kind"] for n in m["nodes"]} >= {"Source", "Segment", "Valve", "Consumer", "Junction"}
    t = sess.get(f"/problems/{inc}/timeline", "operator1")
    steps = [s for s in t["steps"] if s["kind"] == "agent_step"]
    assert steps and {s["chooser"] for s in steps} == {"rules"} and all(s["task"] for s in steps)
    assert all(s["fallback"] is None for s in steps)
    assert [x["kind"] for x in t["chain"]] == ["triage", "investigate", "plan", "dispatch", "verify", "record"]
    for user in ("staff1", "tech1", "meters1"):
        assert sess.get(f"/problems/{inc}", user, expect=403)


def test_other_customer_cannot_see_the_problem(helped):
    out, sess, c = helped
    other = fresh_tenant()
    try:
        from app.cli import bootstrap

        bootstrap(other, password=PASSWORD)
        b = Session(other, PASSWORD)
        for path in (f"/problems/{out['incident']}", f"/problems/{out['incident']}/map", f"/problems/{out['incident']}/timeline"):
            assert b.get(path, "operator1", expect=404)
        assert b.get("/problems", "operator1") == []
    finally:
        TenantGraph(other).delete()


def test_settings_are_manager_only_bounded_and_audited(helped):
    out, sess, c = helped
    assert sess.c.put("/policies/POL-DC-1", json={"changes": {"max_auto_operations": 3}},
                      headers=sess.headers("operator1")).status_code == 403
    for bad in ({"max_auto_operations": 99}, {"frozen": True}, {"min_confidence": "lots"}, {}):
        assert sess.c.put("/policies/POL-DC-1", json={"changes": bad}, headers=sess.headers("manager1")).status_code == 422
    r = sess.c.put("/policies/POL-DC-1", json={"changes": {"max_auto_operations": 3}}, headers=sess.headers("manager1"))
    assert r.status_code == 200 and r.json()["max_auto_operations"] == 3
    assert sess.post("/policies/POL-DC-1/pause", "manager1", {"paused": True})["frozen"] is True
    assert sess.post("/policies/POL-DC-1/pause", "operator1", {"paused": False}, expect=403)
    pol = sess.get("/policies", "operator1")[0]
    reasons = [h["reason"] for h in pol["history"]]
    assert reasons == ["auto_mode_paused", "settings_changed"]
    assert pol["history"][1]["detail"] == {"max_auto_operations": {"from": 2, "to": 3}}


def test_learning_and_reviews(helped):
    out, sess, c = helped
    learned = sess.get("/learned", "operator1")
    assert learned["playbooks"][0]["successes"] == 1 and learned["names"]["SEG-A1"] == "Row A branch pipe"
    rev = sess.get("/review", "manager1")
    assert rev["on_their_own"] == []  # S1 was approved by a person
    assert sess.post("/reviews/REV-NOPE/resolve", "manager1", expect=409)
    assert sess.post("/facts/F-NOPE/confirm", "manager1", expect=404)
    assert sess.post("/facts/F-NOPE/confirm", "operator1", expect=403)


def test_crew_steps_are_for_field_crew(helped):
    out, sess, c = helped
    assert sess.get("/crew/steps", "tech1") == []  # S1 is finished: nothing waiting
    assert sess.get("/crew/steps", "operator1", expect=403)
    jobs = sess.get("/work-orders", "tech1")
    assert jobs and all(j["kind"] == "inspect" for j in jobs) and jobs[0]["target_name"] == "Row A"


def test_waiting_valve_step_shows_who_approved(monkeypatch):
    t = fresh_tenant()
    try:
        out = run("s1", t, seed=4, reset=True, password=PASSWORD)
        sess = Session(t, PASSWORD)
        did = out["decision"]["decision_id"]
        sess.post(f"/decisions/{did}/approve", "operator2")
        sess.post(f"/decisions/{did}/execute", "operator1")
        steps = sess.get("/crew/steps", "tech1")
        assert [(s["valve"], s["target"], s["status"]) for s in steps] == [("V-09", "open", "open")]
        assert steps[0]["approvers"] == ["operator2"] and steps[0]["authority_level"] == "L3"
    finally:
        TenantGraph(t).delete()
