"""Work orders from a decision, field confirmation by the crew, and the incident report."""

import pytest

from app.graph.client import TenantGraph
from scenario_generator.run import Session, run_helpers
from tests.conftest import fresh_tenant

PASSWORD = "practice-only-password"


@pytest.fixture
def s1_done():
    t = fresh_tenant()
    r = run_helpers("s1", "approve", t, 3, reset=True, password=PASSWORD)
    yield r, Session(t, PASSWORD)
    TenantGraph(t).delete()


def _by_kind(orders):
    return sorted((w["kind"], w["target"], w["assigned_team"], w["status"]) for w in orders)


def test_jobs_come_from_the_committed_plan(s1_done):
    r, sess = s1_done
    assert _by_kind(r["work_orders"]) == [("inspect", "Z-A", None, "open"), ("migrate", "WL-BATCH-12", "T-DATA", "open"),
                                          ("migrate", "WL-DEV-01", "T-DATA", "open")]
    # the field crew sees only field jobs; the operators see all of them
    crew = sess.get("/work-orders", "tech1")
    assert [(w["kind"], w["target"]) for w in crew] == [("inspect", "Z-A")]
    assert len(sess.get(f"/work-orders?incident={r['incident']}", "operator1")) == 3
    assert sess.get("/work-orders", "staff1", expect=403)
    g = TenantGraph(sess.tenant)._g
    assert g.ro_query("MATCH (w:WorkOrder)-[:DERIVED_FROM]->(:Decision {id:$d}) MATCH (w)-[:ON]->(t) RETURN count(t)",
                      {"d": r["final"]["decision"]}).result_set == [[3]]


def test_field_confirmation_step_by_step(s1_done):
    r, sess = s1_done
    wo = sess.get("/work-orders", "tech1")[0]
    assert sess.post(f"/work-orders/{wo['id']}/take", "operator1", expect=403)
    migrate = next(w for w in r["work_orders"] if w["kind"] == "migrate")
    assert sess.post(f"/work-orders/{migrate['id']}/take", "tech1", expect=403)["error"] == "not_a_field_job"
    sess.post(f"/work-orders/{wo['id']}/take", "tech1")
    assert sess.post(f"/work-orders/{wo['id']}/take", "tech2", expect=409)["error"] == "not_open"
    assert sess.post(f"/work-orders/{wo['id']}/confirm", "tech2", {"step": "check the area"}, expect=409)  # not theirs
    assert sess.post(f"/work-orders/{wo['id']}/confirm", "tech1", {"step": "fly"}, expect=409)["error"] == "unknown_step"
    sess.post(f"/work-orders/{wo['id']}/confirm", "tech1", {"step": "check the area", "note": "puddle 1 m wide"})
    early = sess.post(f"/work-orders/{wo['id']}/complete", "tech1", {"findings": "done"}, expect=409)
    assert early["error"] == "cannot_complete" and early["missing"] == ["clean up the water", "reset the leak sensor"]
    for step in ("clean up the water", "reset the leak sensor"):
        sess.post(f"/work-orders/{wo['id']}/confirm", "tech1", {"step": step})
    bad = sess.post(f"/work-orders/{wo['id']}/complete", "tech1", {"stuck_valves": ["V-99"]}, expect=409)
    assert bad["error"] == "unknown_valves"
    done = sess.post(f"/work-orders/{wo['id']}/complete", "tech1",
                     {"findings": "V-09 handle seized while checking the backup link", "stuck_valves": ["V-09"]})
    assert done["status"] == "done" and done["confirmed"] == wo["steps"]
    g = TenantGraph(sess.tenant)._g
    fact = g.ro_query("MATCH (f:Fact {kind:'stuck', status:'active'})-[:ABOUT]->(:Valve {id:'V-09'}) "
                      "MATCH (f)-[:EVIDENCED_BY]->(w:WorkOrder {id:$w}) RETURN f.source", {"w": wo["id"]}).result_set
    assert fact == [["field"]]
    trail = g.ro_query("MATCH (a:AuditEvent)-[:OF]->(:WorkOrder {id:$w}) RETURN a.actor, a.to_status, a.reason "
                       "ORDER BY a.seq", {"w": wo["id"]}).result_set
    assert [x[2] for x in trail] == ["taken", "confirmed: check the area", "confirmed: clean up the water",
                                     "confirmed: reset the leak sensor", "completed"]
    assert {x[0] for x in trail} == {"tech1"}


def test_incident_report_states_graph_facts(s1_done):
    r, sess = s1_done
    rep = sess.get(f"/incidents/{r['incident']}/report", "operator1")
    f = rep["facts"]
    assert rep["prose_by"] == "template" and rep["written_by"] == "record_keeper"
    assert f["status"] == "resolved" and f["zones"] == ["Z-A"] and len(f["reports"]) == 1
    assert [(d["kind"], d["status"]) for d in f["decisions"]] == [("act", "verified")]
    assert [(a["to_state"], a["valve"]) for a in f["actions"]] == [("open", "V-09"), ("closed", "V-01"), ("closed", "V-07")]
    assert [v["passed"] for v in f["verifications"]] == [True]
    assert [h["kind"] for h in f["handoffs"]] == ["triage", "investigate", "plan", "dispatch", "verify", "record"]
    assert len(f["work_orders"]) == 3
    # every claim in the prose is one of those facts
    for needle in (r["incident"], f["decisions"][0]["id"], "open V-09, closed V-01, closed V-07", "passed",
                   "practice data"):
        assert needle in rep["prose"]
    # a person can ask for a fresh report; other customers and roles cannot read it
    again = sess.post(f"/incidents/{r['incident']}/report", "operator1")
    assert again["id"] != rep["id"] and again["prose_by"] == "template"
    assert sess.get(f"/incidents/{r['incident']}/report", "staff1", expect=403)
    other = fresh_tenant()
    try:
        from app.cli import bootstrap

        bootstrap(other, password=PASSWORD)
        assert Session(other, PASSWORD).get(f"/incidents/{r['incident']}/report", "operator1", expect=404)
        assert Session(other, PASSWORD).get(f"/work-orders?incident={r['incident']}", "operator1") == []
    finally:
        TenantGraph(other).delete()


def test_no_report_before_the_record_keeper():
    from scenario_generator.run import run

    t = fresh_tenant()
    try:
        out = run("s1", t, seed=1, reset=True, password=PASSWORD)
        assert Session(t, PASSWORD).get(f"/incidents/{out['incident']}/report", "operator1", expect=404)
    finally:
        TenantGraph(t).delete()
