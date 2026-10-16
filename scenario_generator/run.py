"""Run a scenario end to end through the REST API.

  python -m scenario_generator.run s1 --tenant demo --seed 7 --reset            (in-process API)
  python -m scenario_generator.run s1 --tenant demo --seed 7 --base-url http://localhost:8000
      (against a running server; demo users must exist and LEAKTRACE_DEMO_PASSWORD must be set)
  python -m scenario_generator.run s1 --tenant demo --seed 7 --reset --execute happy
  python -m scenario_generator.run s5 --tenant demo --seed 7 --reset --execute auto

With --reset (in-process only) the tenant graph is wiped and bootstrapped with demo users first.
--import-pack imports the data-centre pack through POST /assets/import (implied by --reset).
After that, every step goes through HTTP routes: pack import (manager), readings (meters account),
report (staff), investigate (operator1), approve (operator2), execute (operator1), valve moves (field crew
tech1/tech2 working the simulated plant), readings after the moves (meters account), status and audit.

--execute variants:
  s1: happy            approve, execute, verify
      stuck_v09        V-09 does not move: the plan fails at its first step, nothing to undo, replan
      stuck_v07        V-07 does not move after two moves are done: fail, undo both, replan
      worker_dies      a crew member moves a valve and vanishes; the lease runs out, a second one finishes
      graph_changes    the leak grows after approval: execute is refused as stale, a new plan is approved
      approval_expires the approval runs out before execute; approve again and finish
  s5: auto             handled automatically: no person approves
      passing_valve    V-04 reports closed but still passes water: verification fails, undone automatically

--helpers VARIANT runs the same events but lets the six helpers (Intake, Investigator, Planner, Dispatcher,
Checker, Record keeper) do the work through Task hand-offs, instead of calling /investigate:
  s1: approve          the plan waits for operator2's OK, then runs and is verified
      stuck_v09        approved, V-09 does not move: failed, reported
  s2: evidence         weak evidence: the Investigator asks for someone to look
  s5: auto             handled automatically and verified
      passing_valve    verification fails, undone automatically, the new plan goes to people
--helper-process runs each helper round as a new process (the helpers keep nothing between runs).
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from scenario_generator.field import FieldWorker
from scenario_generator.plant import Plant
from scenario_generator.scenarios import SCENARIOS, s1_leak_update

PACK = Path(__file__).resolve().parents[1] / "packs" / "datacenter" / "topology.json"
VARIANTS = {"s1": ("happy", "stuck_v09", "stuck_v07", "worker_dies", "graph_changes", "approval_expires"),
            "s5": ("auto", "passing_valve")}
HELPER_VARIANTS = {"s1": ("approve", "stuck_v09"), "s2": ("evidence",), "s5": ("auto", "passing_valve")}
ROOT = Path(__file__).resolve().parents[1]


def client(base_url: str | None):
    if base_url:
        import httpx

        return httpx.Client(base_url=base_url, timeout=60)
    from fastapi.testclient import TestClient

    from app.api.main import app

    return TestClient(app)


class Session:
    """One tenant, one HTTP client, a login token per demo user."""

    def __init__(self, tenant: str, password: str, base_url: str | None = None):
        self.c, self.tenant, self.password = client(base_url), tenant, password
        self.tokens: dict[str, str] = {}

    def headers(self, user: str) -> dict:
        if user not in self.tokens:
            r = self.c.post("/auth/login", json={"tenant": self.tenant, "username": user, "password": self.password})
            self.tokens[user] = self._check(r, None)["token"]
        return {"Authorization": f"Bearer {self.tokens[user]}"}

    @staticmethod
    def _check(resp, expect: int | None):
        if expect is not None:
            if resp.status_code != expect:
                raise RuntimeError(f"{resp.request.method} {resp.request.url.path} -> {resp.status_code} "
                                   f"(expected {expect}): {resp.text}")
        elif resp.status_code >= 400:
            raise RuntimeError(f"{resp.request.method} {resp.request.url.path} -> {resp.status_code}: {resp.text}")
        return resp.json()

    def post(self, path: str, user: str, body: dict | None = None, expect: int | None = None):
        return self._check(self.c.post(path, json=body, headers=self.headers(user)), expect)

    def get(self, path: str, user: str, expect: int | None = None):
        return self._check(self.c.get(path, headers=self.headers(user)), expect)


def _ok(resp):
    return Session._check(resp, None)


def _start(tenant: str, *, reset: bool, base_url: str | None, password: str | None) -> Session:
    if reset:
        if base_url:
            raise ValueError("--reset only works in-process")
        from app.cli import bootstrap

        password = bootstrap(tenant, password=password, reset=True)["password"]
    return Session(tenant, password or os.environ["LEAKTRACE_DEMO_PASSWORD"], base_url)


def _investigate(sess: Session, scen: dict, *, investigate: bool, import_pack: bool) -> dict:
    out = {"scenario": scen["id"], "seed": scen["seed"], "tenant": sess.tenant, "steps": []}
    if import_pack:
        out["import"] = sess.post("/assets/import", "manager1", json.loads(PACK.read_text(encoding="utf-8")))
    incident = None
    for step in scen["steps"]:
        if step["kind"] == "readings":
            r = sess.post("/readings", "meters1", {"readings": step["readings"], "source": "synthetic"})
            incident = incident or next(iter(r["incidents"].values()), None)
        else:
            r = sess.post("/reports", step["as"], {"text": step["text"], "hazard": step["hazard"], "source": "synthetic"})
            incident = incident or r["incident"]
        out["steps"].append({"kind": step["kind"], "result": r})
    out["incident"] = incident
    if investigate and incident:
        out["decision"] = sess.post(f"/incidents/{incident}/investigate", "operator1")
    out["password"] = sess.password
    out["leak_flow"] = scen.get("leak_flow")
    return out


def run(name: str, tenant: str, seed: int, *, reset: bool = False, base_url: str | None = None,
        password: str | None = None, investigate: bool = True, import_pack: bool = False) -> dict:
    sess = _start(tenant, reset=reset, base_url=base_url, password=password)
    return _investigate(sess, SCENARIOS[name](seed), investigate=investigate, import_pack=reset or import_pack)


# ---------------------------------------------------------------- carrying out the decision


def _finish(sess: Session, plant: Plant, decision: str, worker: FieldWorker, rounds: int = 6) -> dict:
    """Let the crew work every open step; when the moves are done, the plant's meters report; repeat for an
    undo. Returns the final status."""
    st = sess.get(f"/decisions/{decision}/status", "operator1")
    for _ in range(rounds):
        worked = worker.drain()
        st = sess.get(f"/decisions/{decision}/status", "operator1")
        if st["status"] == "verifying":
            sess.post("/readings", "meters1", {"readings": plant.readings(time.time()), "source": "synthetic"})
            st = sess.get(f"/decisions/{decision}/status", "operator1")
            continue
        if st["status"] in ("executing", "rolling_back") and worked:
            continue
        break
    return st


def run_execution(name: str, variant: str, tenant: str, seed: int, *, reset: bool = False,
                  base_url: str | None = None, password: str | None = None, import_pack: bool = False,
                  lease_s: int = 30) -> dict:
    if variant not in VARIANTS.get(name, ()):
        raise ValueError(f"no variant {variant!r} for {name}; choose from {VARIANTS.get(name)}")
    sess = _start(tenant, reset=reset, base_url=base_url, password=password)
    scen = SCENARIOS[name](seed)
    out = _investigate(sess, scen, investigate=True, import_pack=reset or import_pack)
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    plant = Plant(pack, seed=seed, leak_segment=scen["leak_segment"], leak_flow=scen["leak_flow"],
                  stuck={"stuck_v09": ["V-09"], "stuck_v07": ["V-07"]}.get(variant, []),
                  passing=["V-04"] if variant == "passing_valve" else [])
    did = out["decision"]["decision_id"]
    res = {"variant": variant, "first_decision": did, "decisions": [did], "refusals": []}
    crew = FieldWorker(sess, "tech1", plant, lease_s)

    if name == "s5":  # auto mode executed it inside the investigate call; nobody approves
        res["auto_execution"] = out["decision"].get("execution")
        st = _finish(sess, plant, did, crew)
    else:
        if variant == "approval_expires":
            sess.post(f"/decisions/{did}/approve", "operator2", {"ttl_s": 1, "note": "short approval"})
            time.sleep(1.3)
            res["refusals"].append(sess.post(f"/decisions/{did}/execute", "operator1", expect=409))
            res["status_after_expiry"] = sess.get(f"/decisions/{did}/status", "operator1")["status"]
        sess.post(f"/decisions/{did}/approve", "operator2", {"note": "practice approval"})
        if variant == "graph_changes":
            grown = round(scen["leak_flow"] + 8.0, 2)
            sess.post("/readings", "meters1", {"readings": s1_leak_update(seed, grown, time.time()), "source": "synthetic"})
            plant.leak_flow = grown
            refused = sess.post(f"/decisions/{did}/execute", "operator1", expect=409)
            res["refusals"].append(refused)
            did = refused["new_decision"]
            res["decisions"].append(did)
            sess.post(f"/decisions/{did}/approve", "operator2", {"note": "re-approved after the graph changed"})
        sess.post(f"/decisions/{did}/execute", "operator1")
        if variant == "worker_dies":
            FieldWorker(sess, "tech1", plant, lease_s=1).work_one(die_after_command=True)
            time.sleep(1.3)
            crew = FieldWorker(sess, "tech2", plant, lease_s)
        st = _finish(sess, plant, did, crew)
        if variant in ("stuck_v09", "stuck_v07"):
            res["failed_status"] = st
            sess.post(f"/decisions/{did}/rollback", "operator1", {"reason": "valve did not move"})
            st = _finish(sess, plant, did, crew)
            res["replan"] = sess.post(f"/decisions/{did}/replan", "operator1")
            res["decisions"].append(res["replan"]["decision_id"])

    res.update(investigation=out, final=st, decision=did,
               audit=sess.get(f"/decisions/{did}/audit", "operator1"),
               plant_moves=plant.moves, plant_valves=dict(plant.valves), password=sess.password)
    return res


# ---------------------------------------------------------------- the helpers do the work


def run_helper_round(tenant: str, *, process: bool = False, chooser: str = "rules") -> dict:
    """One round of the helpers until no step is open. In a new process when `process` (a restart)."""
    if process:
        out = subprocess.run([sys.executable, "-m", "app.agents.worker", "--tenant", tenant, "--chooser", chooser],
                             cwd=ROOT, capture_output=True, text=True, timeout=600)
        if out.returncode != 0:
            raise RuntimeError(f"helpers exited {out.returncode}: {out.stderr[-2000:]}")
        return json.loads(out.stdout)
    from dataclasses import asdict

    from app.agents import choosers, runtime
    from app.graph.client import TenantGraph

    c = choosers.default(chooser)
    steps = [asdict(d) for d in runtime.drain(TenantGraph(tenant), c)]
    return {"pid": os.getpid(), "chooser": c.name, "steps": steps, "model_calls": getattr(c, "calls", 0),
            "fallbacks": getattr(c, "fallbacks", [])}


def _latest_decision(sess: Session, incident: str) -> dict | None:
    ids_ = sess.get(f"/incidents/{incident}", "operator1")["decisions"]
    found = [sess.get(f"/decisions/{d}/status", "operator1") for d in ids_]
    found = [f for f in found if f["status"] != "superseded"] or found
    if not found:
        return None
    return max(found, key=lambda f: sess.get(f"/decisions/{f['decision']}", "operator1")["stored"]["ts"])


def drive_helpers(sess: Session, incident: str, plant: Plant, crew: FieldWorker, *, process: bool = False,
                  approve_as: str | None = "operator2", rounds: int = 10, chooser: str = "rules") -> list[dict]:
    """Helpers, people and the plant take turns until nothing moves: helpers run; a plan waiting for a
    person's OK is approved (once); the crew works open valve steps; after the moves the meters report."""
    log, approved = [], set()
    for _ in range(rounds):
        r = run_helper_round(sess.tenant, process=process, chooser=chooser)
        log.append(r)
        moved = bool(r["steps"])
        d = _latest_decision(sess, incident)
        if d and d["kind"] == "act" and d["status"] == "proposed" and d["authority_level"] == "L3" \
                and approve_as and d["decision"] not in approved:
            sess.post(f"/decisions/{d['decision']}/approve", approve_as, {"note": "approved for the helpers"})
            approved.add(d["decision"])
            continue
        if crew.drain():
            moved = True
        d = _latest_decision(sess, incident)
        if d and d["status"] == "verifying":
            sess.post("/readings", "meters1", {"readings": plant.readings(time.time()), "source": "synthetic"})
            moved = True
        if not moved:
            break
    return log


def run_helpers(name: str, variant: str, tenant: str, seed: int, *, reset: bool = False, base_url: str | None = None,
                password: str | None = None, import_pack: bool = False, process: bool = False,
                lease_s: int = 30, chooser: str = "rules") -> dict:
    if variant not in HELPER_VARIANTS.get(name, ()):
        raise ValueError(f"no helper variant {variant!r} for {name}; choose from {HELPER_VARIANTS.get(name)}")
    sess = _start(tenant, reset=reset, base_url=base_url, password=password)
    scen = SCENARIOS[name](seed)
    out = _investigate(sess, scen, investigate=False, import_pack=reset or import_pack)
    inc = out["incident"]
    plant = Plant(json.loads(PACK.read_text(encoding="utf-8")), seed=seed, leak_segment=scen.get("leak_segment"),
                  leak_flow=scen.get("leak_flow") or 0.0, stuck=["V-09"] if variant == "stuck_v09" else [],
                  passing=["V-04"] if variant == "passing_valve" else [])
    rounds = drive_helpers(sess, inc, plant, FieldWorker(sess, "tech1", plant, lease_s), process=process, chooser=chooser)
    timeline = sess.get(f"/agents/timeline?incident={inc}", "operator1")
    decisions = [sess.get(f"/decisions/{d}/status", "operator1") for d in sess.get(f"/incidents/{inc}", "operator1")["decisions"]]
    report = sess.c.get(f"/incidents/{inc}/report", headers=sess.headers("operator1"))
    return {"scenario": scen["id"], "variant": variant, "seed": seed, "incident": inc, "investigation": out,
            "rounds": rounds, "chain": sess.get(f"/incidents/{inc}/helpers", "operator1"),
            "steps_by_role": _steps_by_role(timeline), "decisions": decisions,
            "final": _latest_decision(sess, inc), "incident_after": sess.get(f"/incidents/{inc}", "operator1"),
            "work_orders": sess.get(f"/work-orders?incident={inc}", "operator1"),
            "report": report.json() if report.status_code == 200 else None,
            "plant_moves": plant.moves, "password": sess.password}


def _steps_by_role(timeline: list[dict]) -> dict:
    out: dict[str, list[str]] = {}
    for e in timeline:
        if e["kind"] == "agent_step":
            out.setdefault(e["actor"], []).append(e["tool"])
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="scenario")
    p.add_argument("scenario", choices=sorted(SCENARIOS))
    p.add_argument("--tenant", default="demo")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--reset", action="store_true")
    p.add_argument("--base-url")
    p.add_argument("--import-pack", action="store_true", help="import the data-centre pack through the API first")
    p.add_argument("--execute", metavar="VARIANT", help="carry the decision out: " +
                   "; ".join(f"{k}: {', '.join(v)}" for k, v in VARIANTS.items()))
    p.add_argument("--helpers", metavar="VARIANT", help="let the helpers do the work: " +
                   "; ".join(f"{k}: {', '.join(v)}" for k, v in HELPER_VARIANTS.items()))
    p.add_argument("--helper-process", action="store_true", help="run each helper round as a new process")
    a = p.parse_args(argv)
    if a.helpers:
        r = run_helpers(a.scenario, a.helpers, a.tenant, a.seed, reset=a.reset, base_url=a.base_url,
                        import_pack=a.import_pack, process=a.helper_process)
        f = r["final"] or {}
        print(json.dumps({
            "scenario": a.scenario, "variant": a.helpers, "seed": a.seed, "incident": r["incident"],
            "problem_status": r["incident_after"]["status"],
            "hand_offs": [f"{c['kind']} ({', '.join(c['agents'])}): {c['status']}" for c in r["chain"]],
            "steps_by_role": r["steps_by_role"],
            "decisions": [f"{d['decision']}: {d['kind']} {d['status']} {d['authority_level']}" for d in r["decisions"]],
            "final": {k: f.get(k) for k in ("decision", "status", "authority_level")},
            "work_orders": [f"{w['kind']} {w['target']}: {w['status']}" for w in r["work_orders"]],
            "report": r["report"] and {"prose_by": r["report"]["prose_by"], "prose": r["report"]["prose"]},
            "helper_processes": sorted({x["pid"] for x in r["rounds"]}),
            "demo_password": r["password"] if a.reset else None,
        }, indent=2, default=str))
        return 0
    if a.execute:
        r = run_execution(a.scenario, a.execute, a.tenant, a.seed, reset=a.reset, base_url=a.base_url,
                          import_pack=a.import_pack)
        f = r["final"]
        print(json.dumps({
            "scenario": a.scenario, "variant": a.execute, "seed": a.seed, "decisions": r["decisions"],
            "refused": [x.get("error") for x in r["refusals"]],
            "final": {k: f[k] for k in ("decision", "status", "outcome", "authority_level")},
            "steps": [f"{t['phase']} {t['seq']}: {t['target']} {t['valve']} -> {t['status']}" for t in f["tasks"]],
            "verification": f["verification"] and {"passed": f["verification"]["passed"],
                                                   "failed_checks": f["verification"]["failed_checks"]},
            "audit": [f"{e['kind']} {e['subject']}: {e['from_status']} -> {e['to_status']} ({e['actor']}: {e['reason']})"
                      for e in r["audit"]],
            "replan": r.get("replan") and {"decision": r["replan"]["decision_id"], "summary": r["replan"]["summary"]},
            "plant_moves": [f"{m['target']} {m['valve']}" for m in r["plant_moves"]],
            "demo_password": r["password"] if a.reset else None,
        }, indent=2, default=str))
        return 0
    out = run(a.scenario, a.tenant, a.seed, reset=a.reset, base_url=a.base_url, import_pack=a.import_pack)
    d = out.get("decision") or {}
    print(json.dumps({
        "scenario": out["scenario"], "seed": out["seed"], "incident": out["incident"], "leak_flow": out["leak_flow"],
        "decision": d.get("decision_id"), "kind": d.get("kind"), "summary": d.get("summary"),
        "confidence": (d.get("suspect") or {}).get("confidence"),
        "authority": d.get("authority"),
        "plans": [{"id": x["id"], "label": x["label"], "passed": x["passed"], "failed": x["failed_checks"],
                   "disruption": x["disruption"]} for x in d.get("plans", [])],
        "tool_sequence": d.get("tool_sequence"),
        "demo_password": out["password"] if a.reset else None,
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
