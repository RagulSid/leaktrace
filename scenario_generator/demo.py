"""Fill the demo customer with practice problems for the screens, through the REST API and the helpers.

  python -m scenario_generator.demo --tenant demo

Resets the tenant, then:
  1. S5: a low-risk leak handled automatically and verified (a closed problem, jobs for people, a proven fix);
  2. the documents, tickets and shift chats are read in; ticket TCK-1042 says the backup link valve V-09 is stuck;
  3. S1: a leak near a key rack. Every rescue plan needs V-09, so the helpers hand the choice to people; people
     patch the pipe by hand and close the problem;
  4. the knowledge update: repair ticket TCK-1077 says V-09 works again;
  5. S1 again: the rescue plan through V-09 is back, waiting for an operator's OK.
Ask LeakTrace can then answer "Why did we avoid valve V-09?" from problem 3, with its sources.
Everything is practice data. Needs LEAKTRACE_DEMO_PASSWORD.
"""

import argparse
import json
import os
import random
import sys
import time

from app import config  # noqa: F401  (loads .env, where LEAKTRACE_DEMO_PASSWORD lives)
from scenario_generator import knowledge
from scenario_generator.field import FieldWorker
from scenario_generator.plant import Plant
from scenario_generator.run import PACK, Session, _investigate, _latest_decision, drive_helpers, run_helpers
from scenario_generator.scenarios import SCENARIOS, _batch, _meters

NORMAL = {"LS-A1": "OK", "LS-A3": "OK", "LS-B1": "OK", "PS-MA": "OK", "PS-MB": "OK"}


def _s1_by_helpers(sess: Session, seed: int, scen: dict | None = None, incident: str | None = None) -> str:
    scen = scen or SCENARIOS["s1"](seed)
    if incident is None:
        incident = _investigate(sess, scen, investigate=False, import_pack=False)["incident"]
    plant = Plant(json.loads(PACK.read_text(encoding="utf-8")), seed=seed, leak_segment="SEG-A1", leak_flow=scen["leak_flow"])
    drive_helpers(sess, incident, plant, FieldWorker(sess, "tech1", plant), approve_as=None, rounds=3)
    return incident


def seed(tenant: str, password: str | None = None) -> dict:
    password = password or os.environ["LEAKTRACE_DEMO_PASSWORD"]
    s5 = run_helpers("s5", "auto", tenant, 3, reset=True, password=password)
    sess = Session(tenant, password)
    # The manager sets the emergency wait to its longest (1 hour) so the "needs your OK" plan stays waiting
    # while people look at it; with the pack's 5 minutes the emergency rule would act on it (as designed).
    sess.c.put("/policies/POL-DC-1", json={"changes": {"break_glass_wait_s": 3600}}, headers=sess.headers("manager1")).raise_for_status()
    knowledge.ingest(sess)
    avoided = _s1_by_helpers(sess, 7)
    sess.post(f"/incidents/{avoided}/close", "operator1", {"reason": "pipe patched by hand; V-09 was out of service"})
    rng = random.Random(11)
    sess.post("/readings", "meters1", {"readings": _batch(time.time(), _meters(rng, 0.0), NORMAL), "source": "synthetic"})
    knowledge.ingest(sess, "update_v09_repaired.json")
    leak = _batch(time.time() + 1, _meters(rng, 11.0), {**NORMAL, "LS-A1": "ALARM", "PS-MA": "ANOMALY"})
    waiting = sess.post("/readings", "meters1", {"readings": leak, "source": "synthetic"})["incidents"]["LS-A1"]
    _s1_by_helpers(sess, 8, incident=waiting)
    d = _latest_decision(sess, waiting) or {}
    return {"auto_problem": s5["incident"], "auto_status": s5["final"]["status"], "avoided_v09_problem": avoided,
            "waiting_problem": waiting, "waiting": {k: d.get(k) for k in ("kind", "status", "authority_level")}}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="demo")
    p.add_argument("--tenant", default="demo")
    a = p.parse_args(argv)
    print(json.dumps(seed(a.tenant)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
