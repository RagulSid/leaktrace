"""Ask LeakTrace: answers from graph queries, with sources, or "I don't know".

1. Resolve the question against the map: exact ids ("V-09") and names ("backup link valve").
2. Pick the search by the question's words (fixed patterns, no model): why a valve was avoided (decision ->
   failed check -> fact -> ticket, plus the procedure that names the valve), who owns it (OWNS), who knows it
   (EXPERT_IN from tickets), what we know about it (facts with what replaced what, tickets, documents), or else
   passages from the vector index that share the question's words.
3. Word the answer: fixed sentences (SAY) with [id] after each claim; or, when a model is set up, the model
   rewrites those sentences and may only keep their [id]s.
4. Check every citation in code: each [id] must exist on this customer's map and be among the results of step 2,
   and there must be at least one. Otherwise the answer is "I don't know", with an offer to ask the field crew.
Nothing here writes to the graph; app/brain/conversation.py saves the turns.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app import config
from app.agents.llm_client import ChatClient, LLMBadOutput, LLMError
from app.brain.embed import content_words, embed
from app.brain.ingest import Resolver
from app.graph.client import TenantGraph, rows

CITE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9#:._-]*)\]")

# Every sentence an answer can contain, in plain words (tests/test_ui_lint.py checks them like copy.ts).
SAY = {
    "dont_know": "I don't know. Nothing on the map answers that yet.",
    "avoided": "We avoided {name} ({id}) because we know it does not move: “{statement}”.",
    "from_ticket": "That comes from maintenance ticket {ticket}: “{title}”.",
    "from_crew": "The field crew reported it on job {job}.",
    "decided": "On problem {problem}, every plan that opens {id} failed the “can be done” check, so the helpers chose {choice}.",
    "procedure": "The procedure {doc} says: “{passage}”",
    "since": "Since then: “{statement}”.",
    "owned": "{name} ({id}) is owned by the {team}.",
    "owned_job": "{job} on {name} is owned by the {team}.",
    "chart": "The ownership chart {doc} says so.",
    "knows": "{person} ({title}, {teams}) has done {jobs} on {name}, the latest on {day}.",
    "know_now": "We know: “{statement}”.",
    "know_was": "Earlier we knew “{statement}”, but that no longer holds.",
    "ticket_latest": "Latest maintenance ticket on {name}: {ticket} “{title}” ({status}).",
    "doc_says": "{title} says: “{passage}”",
    "passage": "{title} says: “{passage}”",
}
CHOICE = {"act": "a plan that does not use it", "escalate": "to hand the choice to people",
          "request_evidence": "to ask for more evidence"}
TICKET_STATUS = {"open": "still open", "closed": "closed"}


def kind_of(labels: list[str] | None) -> str:
    labels = labels or []
    for lb, k in (("Fact", "fact"), ("Ticket", "ticket"), ("SOP", "procedure"), ("Document", "document"),
                  ("Decision", "decision"), ("Message", "chat"), ("Person", "person"), ("Team", "team"),
                  ("Incident", "problem"), ("WorkOrder", "job"), ("Task", "job"), ("Verification", "check")):
        if lb in labels:
            return k
    return "thing"


@dataclass
class Draft:
    intent: str
    subjects: list[str]
    sentences: list[tuple[str, list[str]]] = field(default_factory=list)
    sources: dict[str, dict] = field(default_factory=dict)  # id -> {id, kind, title}

    def say(self, key: str, cites: list[str], **values) -> None:
        self.sentences.append((SAY[key].format(**values), [c for c in cites if c]))

    def source(self, sid: str | None, kind: str, title: str | None = None) -> str | None:
        if sid:
            self.sources.setdefault(sid, {"id": sid, "kind": kind, "title": title})
        return sid

    def text(self) -> str:
        return " ".join(s + "".join(f" [{c}]" for c in cites) for s, cites in self.sentences)


def _day(ts: float | None) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d") if ts else "an unknown day"


def classify(q: str, subjects: list[str]) -> str:
    ql = q.lower()
    if re.search(r"\bwhy\b", ql) and re.search(r"avoid|not use|n.t use|skip|not open|n.t open|ruled out|left out", ql):
        return "why_avoid"
    if re.search(r"\bwho\b", ql) and re.search(r"\b(own|owns|owned|responsible|in charge)\b", ql):
        return "who_owns"
    if re.search(r"\bwho\b", ql) and re.search(r"\b(know|knows|ask|expert|worked|fixed|repaired|best|did)\b", ql):
        return "who_knows"
    return "what_we_know" if subjects else "passages"


def _best_passage(passages: list[str], words: tuple[str, ...]) -> str | None:
    if not passages:
        return None
    return max(passages, key=lambda p: (sum(w in p.lower() for w in words), -passages.index(p)))


def _facts(tg: TenantGraph, d: Draft, about: list[str], ids: list[str]) -> list[dict]:
    out = rows(tg.read("brain_facts", {"about": about, "ids": ids}))
    for f in out:
        d.source(f["id"], "fact", f["statement"])
        for e in f["evidence"]:
            if e.get("id"):
                d.source(e["id"], kind_of([e["label"]]), e.get("title"))
    return out


def why_avoid(tg: TenantGraph, d: Draft, res: Resolver) -> None:
    valve = next((s for s in d.subjects if "Valve" in res.labels.get(s, [])), d.subjects[0] if d.subjects else None)
    if not valve:
        return
    name = res.name_of(valve)
    avoided: dict[str, dict] = {}  # fact id -> decision row that cited it
    for dec in rows(tg.read("brain_decisions_mentioning", {"id": valve})):
        rec = json.loads(dec["explain_json"] or "{}")
        for plan in rec.get("plans") or []:
            for c in plan.get("checks") or []:
                if c.get("code") == "feasible" and not c.get("passed"):
                    for s in (c.get("detail") or {}).get("stuck") or []:
                        if s.get("valve") == valve:
                            for fid in s.get("facts") or []:
                                avoided.setdefault(fid, dec)
    facts = _facts(tg, d, [valve], list(avoided))
    stuck = [f for f in facts if f["kind"] == "stuck" and (f["id"] in avoided or f["status"] == "active")]
    if not stuck:
        return  # nothing on the map explains an avoidance: that is "I don't know"
    f = stuck[0]
    d.say("avoided", [f["id"]], name=name, id=valve, statement=f["statement"])
    for e in f["evidence"]:
        if e["label"] == "Ticket":
            d.say("from_ticket", [e["id"]], ticket=e["id"], title=e.get("title") or "")
        elif e.get("id"):
            d.say("from_crew", [e["id"]], job=e["id"])
    dec = avoided.get(f["id"])
    if dec:
        d.source(dec["id"], "decision", dec["kind"])
        d.source(dec["incident"], "problem")
        d.say("decided", [dec["id"]], problem=dec["incident"], id=valve, choice=CHOICE.get(dec["kind"], dec["kind"]))
    words = ("cannot", "stuck", "never", "seize", "do not")
    sops = [doc for doc in rows(tg.read("brain_docs_mentioning", {"ids": [valve]})) if doc["kind"] == "sop"]
    picked = [(doc, _best_passage(doc["passages"], words)) for doc in sops]
    relevant = [(doc, p) for doc, p in picked if p and any(w in p.lower() for w in words)] or picked[:1]
    for doc, p in relevant[:2]:
        if p:
            d.source(doc["id"], "procedure", doc["title"])
            d.say("procedure", [doc["id"]], doc=doc["id"], passage=p)
    for newer in f["replaced_by"]:
        n = next((x for x in _facts(tg, d, [], [newer])), None)
        if n:
            d.say("since", [n["id"]] + [e["id"] for e in n["evidence"] if e.get("id")], statement=n["statement"])


def who_owns(tg: TenantGraph, d: Draft, res: Resolver) -> None:
    for r in rows(tg.read("brain_owners", {"ids": d.subjects[:3]})):
        charts = [c for c in r["charts"] if c]
        for t in [t for t in r["teams"] if t.get("id")]:
            d.source(t["id"], "team", t["name"])
            d.say("owned", [t["id"]], name=r["name"] or r["id"], id=r["id"], team=t["name"])
        for t in [t for t in r["via_jobs"] if t.get("id")]:
            d.source(t["id"], "team", t["name"])
            d.source(t["workload"], "thing", t["workload_name"])
            d.say("owned_job", [t["id"], t["workload"]], job=t["workload_name"], name=r["name"] or r["id"], team=t["name"])
        for c in charts[:1]:
            if d.sentences:
                d.source(c, "document")
                d.say("chart", [c], doc=c)


def who_knows(tg: TenantGraph, d: Draft, res: Resolver) -> None:
    for e in rows(tg.read("brain_experts", {"ids": d.subjects[:3]}))[:2]:
        d.source(e["id"], "person", e["name"])
        for t in e["tickets"]:
            d.source(t, "ticket")
        jobs = f"{e['jobs']} job" + ("s" if e["jobs"] != 1 else "")
        d.say("knows", [e["id"]] + e["tickets"], person=e["name"], title=e["title"], teams=", ".join(e["teams"]),
              jobs=jobs, name=e["about_name"] or e["about"], day=_day(e["last"]))


def what_we_know(tg: TenantGraph, d: Draft, res: Resolver) -> None:
    subjects = d.subjects[:2]
    for f in _facts(tg, d, subjects, []):
        ev = [e["id"] for e in f["evidence"] if e.get("id")]
        if f["status"] == "active":
            d.say("know_now", [f["id"]] + ev, statement=f["statement"])
        elif f["status"] == "superseded":
            d.say("know_was", [f["id"]] + f["replaced_by"], statement=f["statement"])
    tickets = rows(tg.read("brain_tickets_on", {"ids": subjects}))
    if tickets:
        t = tickets[0]
        d.source(t["id"], "ticket", t["title"])
        d.say("ticket_latest", [t["id"]], name=res.name_of(t["asset"]), ticket=t["id"], title=t["title"],
              status=TICKET_STATUS.get(t["status"], t["status"]))
    for doc in rows(tg.read("brain_docs_mentioning", {"ids": subjects}))[:2]:
        p = _best_passage(doc["passages"], ())
        if p:
            d.source(doc["id"], kind_of(["SOP"] if doc["kind"] == "sop" else ["Document"]), doc["title"])
            d.say("doc_says", [doc["id"]], title=doc["title"], passage=p)


def passages(tg: TenantGraph, d: Draft, question: str) -> None:
    asked = set(content_words(question))
    for r in rows(tg.read("brain_passages", {"k": 5, "vec": embed(question)})):
        shared = asked & set(content_words(r["text"]))
        if r["score"] <= config.ASK_PASSAGE_MAX_DISTANCE and len(shared) >= config.ASK_PASSAGE_MIN_SHARED_WORDS:
            d.source(r["source_id"], kind_of(r["labels"]), r["title"])
            d.say("passage", [r["source_id"]], title=r["title"] or r["source_id"], passage=r["text"])
        if len(d.sentences) >= 2:
            break


SEARCHES = {"why_avoid": why_avoid, "who_owns": who_owns, "who_knows": who_knows, "what_we_know": what_we_know}


def check_citations(tg: TenantGraph, text: str, retrieved: set[str]) -> tuple[list[str], str | None]:
    """The cited ids, and why they fail (None when every one is fine)."""
    cites = list(dict.fromkeys(CITE.findall(text)))
    if not cites:
        return cites, "no_citations"
    if set(cites) - retrieved:
        return cites, "cited_unretrieved"
    on_map = {r["id"] for r in rows(tg.read("brain_nodes_exist", {"ids": cites}))}
    if set(cites) - on_map:
        return cites, "cited_missing"
    return cites, None


def default_phraser() -> ChatClient | None:
    if config.ASK_PHRASER == "template":
        return None
    if all((config.LLM_BASE_URL, config.LLM_API_KEY, config.LLM_MODEL)):
        return ChatClient()
    return None


PHRASE_PROMPT = ("You reword answers for people running a data hall cooling loop. Rewrite the draft in plain, short "
                 "sentences. Use only what the draft and sources say. Keep every [id] exactly as written, after the "
                 "claim it supports. Do not add ids, numbers or claims. Reply with the answer text only.")


def _phrase(client: ChatClient, question: str, draft: Draft) -> str:
    msg = json.dumps({"question": question, "draft": draft.text(), "sources": list(draft.sources.values())})
    reply = client.chat([{"role": "system", "content": PHRASE_PROMPT}, {"role": "user", "content": msg}], max_tokens=400)
    if not reply.text.strip():
        raise LLMBadOutput("empty answer")
    return reply.text.strip()


def _why(e: LLMError) -> str:
    return e.reason


def ask(tg: TenantGraph, question: str, phraser: ChatClient | None | bool = True) -> dict:
    """phraser: True = the configured default; None/False = templates only; or a ChatClient."""
    res = Resolver(tg)
    subjects, _ = res.find(question)
    subjects = [s for s in subjects if s in res.ids]
    d = Draft(classify(question, subjects), subjects)
    if d.intent in SEARCHES:
        SEARCHES[d.intent](tg, d, res)
    if not d.sentences and d.intent in ("what_we_know", "passages"):
        passages(tg, d, question)  # a "why" or "who" question is not answered by a passage that shares its words
    base = {"question": question, "intent": d.intent, "subjects": subjects}
    if not d.sentences:
        return {**base, **_dont_know("nothing_found")}
    client = default_phraser() if phraser is True else (phraser or None)
    text, by, fallback = d.text(), "template", None
    if client is not None:
        try:
            text, by = _phrase(client, question, d), client.model
        except LLMError as e:
            text, fallback = d.text(), _why(e)
    cites, bad = check_citations(tg, text, set(d.sources))
    if bad:
        return {**base, **_dont_know(bad), "phrased_by": by}
    return {**base, "known": True, "answer": text, "cites": [d.sources[c] for c in cites], "phrased_by": by,
            "fallback": fallback, "offer": None}


def _dont_know(why: str) -> dict:
    return {"known": False, "answer": SAY["dont_know"], "cites": [], "phrased_by": "template", "fallback": why,
            "offer": "ask_crew"}
