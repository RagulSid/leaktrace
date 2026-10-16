"""Ask LeakTrace (S9): answers from graph queries with sources that code checks, "I don't know" otherwise, a
knowledge update that changes later answers (and the next plan), and saved conversations that survive a restart."""

import json
import os
import subprocess
import sys

import pytest

from app.agents.llm_client import ChatReply, LLMRateLimited
from app.brain import ask as brain
from app.graph.client import TenantGraph, rows
from scenario_generator import knowledge
from scenario_generator.run import Session, _latest_decision
from tests.conftest import fresh_tenant

PASSWORD = "practice-only-password"
V09 = "Why did we avoid valve V-09?"


@pytest.fixture(scope="module")
def s9():
    """The corpus read in, then an S1 leak the helpers hand to people because V-09 is known to be stuck."""
    t = fresh_tenant()
    out = knowledge.run_s9(t, 7, reset=True, password=PASSWORD, update=False)
    yield out, Session(t, PASSWORD), TenantGraph(t)
    TenantGraph(t).delete()


class FakeModel:
    """Stands in for a chat model: returns a fixed rewrite of the draft (no network)."""

    def __init__(self, rewrite, model="fake-model"):
        self.rewrite, self.model, self.calls = rewrite, model, 0

    def chat(self, messages, tools=None, max_tokens=None):
        self.calls += 1
        if isinstance(self.rewrite, Exception):
            raise self.rewrite
        return ChatReply(self.rewrite(json.loads(messages[1]["content"])["draft"]), [])


def test_corpus_is_read_into_the_map(s9):
    out, _, tg = s9
    i = out["ingest"]
    assert (i["documents"], i["tickets"], i["messages"], i["people"]) == (6, 10, 20, 6)
    assert i["facts"] == ["F-TCK-1042"] and i["reviews"] == 1  # V-11 is not on the map: a manager checks it
    counts = rows(tg.read("stats"))[0]
    assert tg._g.ro_query("MATCH (:Ticket {id:'TCK-1042'})-[:ON]->(v:Valve) RETURN v.id").result_set == [["V-09"]]
    assert tg._g.ro_query("MATCH (s:SOP) RETURN count(s)").result_set == [[2]]
    assert tg._g.ro_query("MATCH (c:Chunk)-[:PART_OF]->() RETURN count(c)").result_set == [[48]]
    # reading the same corpus again changes nothing
    again = knowledge.ingest(Session(tg.tenant, PASSWORD))
    assert again["facts"] == ["F-TCK-1042"] and rows(tg.read("stats"))[0] == counts


def test_why_did_we_avoid_v09_cites_a_ticket_a_thing_we_know_and_a_procedure(s9):
    out, sess, tg = s9
    assert out["decision"]["kind"] == "escalate"  # without the ticket this is the rescue plan through V-09
    a = out["before"][V09]
    kinds = {c["kind"] for c in a["cites"]}
    ids = [c["id"] for c in a["cites"]]
    assert a["known"] and {"ticket", "fact", "procedure"} <= kinds
    assert "TCK-1042" in ids and "F-TCK-1042" in ids and "SOP-ISO-01" in ids and out["decision"]["decision"] in ids
    # every cited id is on this customer's map
    assert {r["id"] for r in rows(tg.read("brain_nodes_exist", {"ids": ids}))} == set(ids)
    assert a["phrased_by"] == "template" and "[TCK-1042]" in a["answer"]


def test_who_owns_and_who_knows_come_from_the_map(s9):
    out, _, _ = s9
    own = out["before"]["Who owns V-09?"]
    assert own["known"] and [c["id"] for c in own["cites"]][:1] == ["T-FAC"]
    rack = out["before"]["Who owns Rack A1?"]
    assert {"T-ML", "WL-TRAIN-07"} <= {c["id"] for c in rack["cites"]}
    knows = out["before"]["Who knows the backup link valve best?"]
    assert knows["known"] and knows["cites"][0]["id"] == "P-01" and "Dana Reyes" in knows["answer"]


def test_unsupported_questions_get_i_dont_know_and_an_offer(s9):
    out, sess, _ = s9
    a = out["before"]["What is the capital of France?"]
    assert a == {**a, "known": False, "cites": [], "offer": "ask_crew", "answer": brain.SAY["dont_know"]}
    for q in ("Why did we avoid valve V-02?", "Who knows the dev sandbox?"):
        r = knowledge.ask(sess, q)
        assert not r["known"] and r["cites"] == [] and r["offer"] == "ask_crew", q
    # the offer: a "find out" job the field crew sees and can finish
    job = sess.post("/brain/find-out", "operator1", {"question": "Is V-02 still sticky?", "target": "V-02",
                                                      "incident": out["incident"]})["work_order"]
    mine = sess.get("/work-orders", "tech1")
    assert [j["kind"] for j in mine if j["id"] == job] == ["find_out"]
    sess.post(f"/work-orders/{job}/take", "tech1")
    for step in ("find out the answer", "write down what you found"):
        sess.post(f"/work-orders/{job}/confirm", "tech1", {"step": step})
    assert sess.post(f"/work-orders/{job}/complete", "tech1", {"findings": "moves fine"})["status"] == "done"
    assert sess.post("/brain/find-out", "staff1", {"question": "anything"}, expect=403)


def test_citations_are_checked_in_code(s9):
    out, sess, tg = s9
    keep = FakeModel(lambda draft: "Reworded. " + draft)
    r = brain.ask(tg, V09, phraser=keep)
    assert r["known"] and r["phrased_by"] == "fake-model" and keep.calls == 1
    for rewrite, why in ((lambda d: d + " Also [P-02] agrees.", "cited_unretrieved"),  # on the map, not retrieved
                         (lambda d: d + " See [V-01].", "cited_unretrieved"),
                         (lambda d: "V-09 is stuck, trust me.", "no_citations")):
        r = brain.ask(tg, V09, phraser=FakeModel(rewrite))
        assert (r["known"], r["fallback"], r["cites"], r["offer"]) == (False, why, [], "ask_crew")
        assert r["phrased_by"] == "fake-model"
    # an id that is retrieved but not on this map (cannot come from a search, so checked directly)
    assert brain.check_citations(tg, "x [NOPE-1]", {"NOPE-1"}) == (["NOPE-1"], "cited_missing")
    # the model fails: the fixed sentences answer, and the record says why
    r = brain.ask(tg, V09, phraser=FakeModel(LLMRateLimited("429")))
    assert r["known"] and r["phrased_by"] == "template" and r["fallback"] == "rate_limited"


def test_another_customer_gets_no_answer_from_this_one(s9):
    out, _, tg = s9
    other = fresh_tenant()
    try:
        from app.cli import bootstrap
        bootstrap(other, password=PASSWORD)
        b = Session(other, PASSWORD)
        b.post("/assets/import", "manager1", json.loads(knowledge.PACK.read_text(encoding="utf-8")))
        r = knowledge.ask(b, V09)
        assert not r["known"] and r["cites"] == []
        ids = [c["id"] for c in out["before"][V09]["cites"]]
        assert brain.check_citations(TenantGraph(other), " ".join(f"[{i}]" for i in ids), set(ids))[1] == "cited_missing"
    finally:
        TenantGraph(other).delete()


def test_manager_sees_the_unmatched_name(s9):
    _, sess, _ = s9
    k = sess.get("/review", "manager1")["knowledge"]
    assert [(x["source_id"], json.loads(x["detail"])["word"]) for x in k] == [("PM-LOOP", "V-11")]
    assert sess.post("/brain/ingest", "operator1", {"documents": []}, expect=403)
    bad = {"tickets": [{"id": "TCK-9", "asset": "V-99", "title": "x", "text": "x"}]}
    assert sess.post("/brain/ingest", "manager1", bad, expect=422)


def test_conversation_is_saved_per_person_and_problem_and_resumes_after_a_restart(s9):
    out, sess, tg = s9
    inc = out["incident"]
    sess.post("/brain/ask", "manager1", {"question": "Who owns V-09?", "incident": inc})
    sess.post("/brain/ask", "manager1", {"question": "What is the capital of France?", "incident": inc})
    h = sess.get(f"/brain/conversation?incident={inc}", "manager1")
    assert [m["role"] for m in h["messages"]] == ["user", "assistant", "user", "assistant"]
    assert h["messages"][1]["cites"][:1] == [{"id": "T-FAC", "kind": "team", "title": "Cooling operations team"}]
    assert h["messages"][3]["known"] is False
    assert sess.get("/brain/conversation", "manager1")["messages"] == []  # the general conversation is separate
    assert len(sess.get(f"/brain/conversation?incident={inc}", "operator1")["messages"]) >= 12  # run_s9's questions
    assert sess.get(f"/brain/conversation?incident={inc}", "staff1", expect=403)
    # a new process (nothing in memory) reads the same conversation from FalkorDB
    code = ("import json,sys; from scenario_generator.run import Session; "
            "s = Session(sys.argv[1], sys.argv[2]); "
            "print(json.dumps(s.get('/brain/conversation?incident=' + sys.argv[3], 'manager1')))")
    res = subprocess.run([sys.executable, "-c", code, tg.tenant, PASSWORD, inc], capture_output=True, text=True,
                         timeout=120, env={**os.environ, "FALKORDB_CONNECT_TIMEOUT_S": "2"})
    assert res.returncode == 0, res.stderr[-2000:]
    assert json.loads(res.stdout.strip().splitlines()[-1]) == h


def test_knowledge_update_changes_later_answers_and_the_next_plan():
    t = fresh_tenant()
    try:
        out = knowledge.run_s9(t, 7, reset=True, password=PASSWORD, update=True)
        sess = Session(t, PASSWORD)
        assert out["update"]["superseded"] == ["F-TCK-1042"] and out["update"]["facts"] == ["F-TCK-1077"]
        before, after = out["before"]["What do we know about V-09?"], out["after"]["What do we know about V-09?"]
        assert before["answer"] != after["answer"]
        assert "F-TCK-1077" not in {c["id"] for c in before["cites"]} and "TCK-1077" in {c["id"] for c in after["cites"]}
        assert "no longer holds" in after["answer"]
        why = out["after"][V09]
        assert why["known"] and "F-TCK-1077" in {c["id"] for c in why["cites"]}  # "since then: it works again"
        knows = out["after"]["Who knows the backup link valve best?"]["answer"]
        assert "2 jobs" in knows
        # the old fact is kept, marked replaced
        tg = TenantGraph(t)
        assert tg._g.ro_query("MATCH (n:Fact {id:'F-TCK-1077'})-[:SUPERSEDES]->(o:Fact {id:'F-TCK-1042'}) "
                              "RETURN o.status").result_set == [["superseded"]]
        # confirming the replaced fact would quietly bring the stuck valve back: refused
        assert sess.post("/facts/F-TCK-1042/confirm", "manager1", expect=409)
        learned = {f["id"]: f["status"] for f in sess.get("/learned", "manager1")["facts"]}
        assert learned["F-TCK-1042"] == "superseded" and learned["F-TCK-1077"] == "active"
        # planning again now uses V-09: the rescue plan needs a person's OK instead of handing the choice to people
        sess.post(f"/incidents/{out['incident']}/investigate", "operator1")
        d = _latest_decision(sess, out["incident"])
        rec = sess.get(f"/decisions/{d['decision']}", "operator1")
        assert d["kind"] == "act" and d["authority_level"] == "L3"
        assert "open V-09" in next(p["label"] for p in rec["plans"] if p["id"] == rec["chosen"])
    finally:
        TenantGraph(t).delete()


def test_demo_seed_tells_the_v09_story():
    from scenario_generator.demo import seed

    t = fresh_tenant()
    try:
        out = seed(t, PASSWORD)
        assert out["auto_status"] == "verified" and out["waiting"] == {"kind": "act", "status": "proposed", "authority_level": "L3"}
        sess = Session(t, PASSWORD)
        assert sess.get(f"/incidents/{out['avoided_v09_problem']}", "operator1")["status"] == "closed"
        a = knowledge.ask(sess, V09)
        decisions = [c for c in a["cites"] if c["kind"] == "decision"]
        assert a["known"] and decisions and {"F-TCK-1042", "TCK-1042", "F-TCK-1077"} <= {c["id"] for c in a["cites"]}
    finally:
        TenantGraph(t).delete()
