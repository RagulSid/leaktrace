"""S9: company knowledge in the same graph as the map, through the REST API.

  python -m scenario_generator.knowledge --tenant s9demo --reset

1. Import the practice map, then read in the synthetic corpus (docs_corpus/corpus.json: 6 documents, 10 tickets,
   20 shift-chat messages, people, teams and ownership). Ticket TCK-1042 says the backup link valve V-09 failed to
   open, so the Record keeper records that V-09 does not move.
2. An S1 leak on the Row A branch pipe: the rescue plan needs V-09, so every plan that opens it fails its "can be
   done" check and the helpers hand the choice to people.
3. Ask LeakTrace "Why did we avoid valve V-09?" and other questions.
4. The knowledge update (docs_corpus/update_v09_repaired.json): repair ticket TCK-1077 replaces what we knew, and
   the same question about V-09 gets a different answer.
Everything is practice data (source: synthetic).
"""

import argparse
import json
import sys
from pathlib import Path

from app import config  # noqa: F401  (loads .env)
from scenario_generator.field import FieldWorker
from scenario_generator.plant import Plant
from scenario_generator.run import PACK, Session, _investigate, _latest_decision, _start, drive_helpers
from scenario_generator.scenarios import SCENARIOS

CORPUS = Path(__file__).resolve().parent / "docs_corpus"
QUESTIONS = ["Why did we avoid valve V-09?", "Who owns V-09?", "Who knows the backup link valve best?",
             "What do we know about V-09?", "Who owns Rack A1?", "What is the capital of France?"]


def load(name: str) -> dict:
    return json.loads((CORPUS / name).read_text(encoding="utf-8"))


def ingest(sess: Session, name: str = "corpus.json") -> dict:
    return sess.post("/brain/ingest", "manager1", load(name))


def ask(sess: Session, question: str, user: str = "operator1", incident: str | None = None) -> dict:
    return sess.post("/brain/ask", user, {"question": question, "incident": incident})


def run_s9(tenant: str, seed: int = 7, *, reset: bool = True, password: str | None = None,
           base_url: str | None = None, update: bool = True) -> dict:
    sess = _start(tenant, reset=reset, base_url=base_url, password=password)
    sess.post("/assets/import", "manager1", json.loads(PACK.read_text(encoding="utf-8")))
    out = {"tenant": tenant, "ingest": ingest(sess)}
    scen = SCENARIOS["s1"](seed)
    inv = _investigate(sess, scen, investigate=False, import_pack=False)
    plant = Plant(json.loads(PACK.read_text(encoding="utf-8")), seed=seed, leak_segment="SEG-A1",
                  leak_flow=scen["leak_flow"])
    drive_helpers(sess, inv["incident"], plant, FieldWorker(sess, "tech1", plant), approve_as=None, rounds=4)
    out["incident"], out["decision"] = inv["incident"], _latest_decision(sess, inv["incident"])
    out["before"] = {q: ask(sess, q, incident=inv["incident"]) for q in QUESTIONS}
    if update:
        out["update"] = ingest(sess, "update_v09_repaired.json")
        out["after"] = {q: ask(sess, q, incident=inv["incident"]) for q in QUESTIONS[:4]}
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="knowledge")
    p.add_argument("--tenant", default="s9demo")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--reset", action="store_true")
    p.add_argument("--no-update", action="store_true")
    a = p.parse_args(argv)
    r = run_s9(a.tenant, a.seed, reset=a.reset, update=not a.no_update)
    short = lambda res: {q: {"known": x["known"], "answer": x["answer"], "cites": [c["id"] for c in x["cites"]]}  # noqa: E731
                         for q, x in res.items()}
    print(json.dumps({"ingest": r["ingest"], "incident": r["incident"],
                      "decision": {k: (r["decision"] or {}).get(k) for k in ("decision", "kind", "authority_level")},
                      "before": short(r["before"]), "update": r.get("update"), "after": short(r.get("after") or {})},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
