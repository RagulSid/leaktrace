"""Ablation and baselines: the same cases decided four ways, each scored by the same simulated plant.

  python -m scenario_generator.evaluate --seeds 5            # writes app/data/evaluation.json

Approaches (all see the same evidence: which leak sensor alarms, so which pipe section is suspected):
  graph   LeakTrace itself, through its REST API: multi-hop searches, algo.maxFlow per plan, memory, authority.
          Its committed plan is scored (a plan that needs a person's OK is scored as if approved).
  flat    a fixed rule on flat tables. It does NOT run LeakTrace's checks: it closes the valves next to the
          suspected section, counts as affected only racks fed directly by that section, skips a valve with an
          open failed-to-operate ticket, and asks a person only if a directly fed rack is a key rack. One lookup
          per table, no paths, no max flow. It is close to B1, not "LeakTrace without the graph".
  B1      close the nearest valve upstream of the suspected section.
  B2      isolate the whole loop (close every valve).
Not run: B3 (a language model with flat tables): no model key was set.

Cases: S1 (leak on the Row A branch pipe; the rescue needs the backup link V-09), S5 (small leak on the Rack A2
feed), S3 (S1 when V-09 is known stuck from ticket TCK-1042 and really is stuck in the plant).
Scored by scenario_generator/plant.py, which knows nothing about the app: after the moves, is water still going to
the leak, and which racks get less than they need (key racks are criticality 5).
Everything is practice data.
"""

import argparse
import json
import platform
import sys
import time
from pathlib import Path

from app import config  # noqa: F401  (loads .env)
from app.graph import client as graph_client
from app.graph.client import TenantGraph
from scenario_generator import knowledge
from scenario_generator.plant import Plant
from scenario_generator.run import PACK, _investigate, _latest_decision, _start
from scenario_generator.scenarios import SCENARIOS

OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "evaluation.json"
CASES = {"S1": ("s1", False), "S5": ("s5", False), "S3": ("s1", True)}
KEY = 5  # criticality of racks that must keep running
PASSWORD = "practice-only-evaluation"


def _pack() -> dict:
    return json.loads(PACK.read_text(encoding="utf-8"))


def _suspect(scen: dict, pack: dict) -> str:
    """The section the alarmed leak sensor watches (the same evidence for every approach)."""
    watches = {ln["from"]: ln["to"] for ln in pack["links"] if ln["type"] == "MONITORS"}
    alarmed = [r["id"] for s in scen["steps"] if s["kind"] == "readings" for r in s["readings"] if r.get("state") == "ALARM"]
    return watches[alarmed[-1]]


# ---------------------------------------------------------------- the four approaches

def graph(case: str, seed: int) -> dict:
    name, stuck_known = CASES[case]
    tenant = f"t_eval_{case.lower()}_{seed}"
    try:
        sess = _start(tenant, reset=True, base_url=None, password=PASSWORD)
        sess.post("/assets/import", "manager1", _pack())
        if stuck_known:
            knowledge.ingest(sess)
        scen = SCENARIOS[name](seed)
        inv = _investigate(sess, scen, investigate=False, import_pack=False)
        graph_client.QUERY_LOG.clear()
        t0 = time.perf_counter()
        sess.post(f"/incidents/{inv['incident']}/investigate", "operator1")
        ms = (time.perf_counter() - t0) * 1000
        log = list(graph_client.QUERY_LOG)
        d = _latest_decision(sess, inv["incident"])
        rec = sess.get(f"/decisions/{d['decision']}", "operator1")
        chosen = next((p for p in rec.get("plans") or [] if p["id"] == rec.get("chosen")), None)
        moves = []
        if d["kind"] == "act" and chosen:
            moves = [(s.split(":", 1)[1], "closed" if s.startswith("close:") else "open")
                     for s in chosen["ops"] if s.startswith(("close:", "open:"))]
        return {"moves": moves, "asked_person": d["authority_level"] in ("L3", "L4") or d["kind"] != "act",
                "decision": d["kind"], "level": d["authority_level"], "lookups": len(log),
                "max_flow_calls": sum(1 for e in log if "max_flow" in e.query), "errors": sum(1 for e in log if e.error),
                "ms": round(ms, 1)}
    finally:
        TenantGraph(tenant).delete()


def flat(scen: dict, pack: dict, tickets: list[dict]) -> dict:
    """Flat tables: pipes(from, to), valves(id), racks(id, criticality), sensors(id, watches), tickets(asset, code)."""
    lookups = 0
    suspect = _suspect(scen, pack); lookups += 2  # alarm table, sensor table
    valves = {n["id"] for n in pack["nodes"] if "Valve" in n["labels"]}
    pipes = [(f["from"], f["to"]) for f in pack["flows"]]
    near = {b for a, b in pipes if a == suspect} | {a for a, b in pipes if b == suspect}; lookups += 1
    racks = {n["id"]: n["props"].get("criticality", 0) for n in pack["nodes"] if "Consumer" in n["labels"]}
    affected = [r for r in near if r in racks]; lookups += 1
    to_close = sorted(near & valves)
    blocked = {t["asset"] for t in tickets if t.get("problem_code") == "valve_failed_to_operate" and t.get("status") == "open"}
    lookups += 1
    to_close = [v for v in to_close if v not in blocked]
    asked = any(racks[r] >= KEY for r in affected) or not to_close
    return {"moves": [(v, "closed") for v in to_close], "asked_person": asked, "decision": "act", "lookups": lookups,
            "max_flow_calls": 0, "errors": 0}


def nearest_valve(scen: dict, pack: dict) -> dict:
    suspect = _suspect(scen, pack)
    valve = next(f["valve_id"] for f in pack["flows"] if f["to"] == suspect and f.get("valve_id"))
    return {"moves": [(valve, "closed")], "asked_person": False, "decision": "act", "lookups": 2, "max_flow_calls": 0,
            "errors": 0}


def whole_loop(scen: dict, pack: dict) -> dict:
    vs = sorted(n["id"] for n in pack["nodes"] if "Valve" in n["labels"] and n["props"]["state"] == "open")
    return {"moves": [(v, "closed") for v in vs], "asked_person": False, "decision": "act", "lookups": 1,
            "max_flow_calls": 0, "errors": 0}


# ---------------------------------------------------------------- scoring by the plant

def score(pack: dict, scen: dict, stuck: list[str], moves: list[tuple[str, str]]) -> dict:
    plant = Plant(pack, seed=scen["seed"], leak_segment=scen["leak_segment"], leak_flow=scen["leak_flow"], stuck=stuck)
    failed = [v for i, (v, target) in enumerate(moves) if not plant.command(f"eval-{i}", v, target)["ok"]]
    s = plant.solve()
    need = {n["id"]: (n["props"]["required_flow"], n["props"].get("criticality", 0)) for n in pack["nodes"] if "Consumer" in n["labels"]}
    short = {r: round(req - s["racks"][r], 3) for r, (req, _) in need.items() if s["racks"][r] < req - 1e-6}
    return {"leak_stopped": s["leak"] <= 1e-6, "leak_flow_left": round(s["leak"], 3),
            "key_racks_short": sorted(r for r in short if need[r][1] >= KEY), "racks_short": sorted(short),
            "weighted_shortfall": round(sum(need[r][1] * short[r] / need[r][0] for r in short), 3),
            "moves": len(moves), "moves_failed": failed}


def run(seeds: int) -> dict:
    pack = _pack()
    tickets = knowledge.load("corpus.json")["tickets"]
    rows = []
    for case, (name, stuck_known) in CASES.items():
        for seed in range(1, seeds + 1):
            scen = SCENARIOS[name](seed)
            stuck = ["V-09"] if stuck_known else []
            decided = {"graph": graph(case, seed), "flat": flat(scen, pack, tickets if stuck_known else []),
                       "B1": nearest_valve(scen, pack), "B2": whole_loop(scen, pack)}
            for approach, d in decided.items():
                moves = d.pop("moves")
                rows.append({"case": case, "seed": seed, "approach": approach, **d,
                             "moves_list": [f"{'close' if t == 'closed' else 'open'} {v}" for v, t in moves],
                             **score(pack, scen, stuck, moves)})
    return rows


def notes(summary: list[dict]) -> dict:
    """One plain sentence per case, worked out from the numbers (never typed by hand)."""
    s = {(r["case"], r["approach"]): r for r in summary}
    same = ("leak_stopped", "key_rack_short_runs", "racks_short_avg", "moves_avg")
    out = {}
    for case in CASES:
        g, f, b1 = s[(case, "graph")], s[(case, "flat")], s[(case, "B1")]
        if all(g[k] == f[k] == b1[k] for k in same):
            out[case] = "No difference: LeakTrace, the flat-table rule and B1 made the same moves with the same result."
        elif g["leak_stopped"] < g["runs"] and g["key_rack_short_runs"] == 0 and g["asked_person"] == g["runs"]:
            out[case] = ("LeakTrace avoids starving the key rack and asks a person; it does not stop the leak on its "
                         f"own. The others stop the leak and leave a key rack short in {f['key_rack_short_runs']} of "
                         f"{f['runs']} runs (flat) and {b1['key_rack_short_runs']} of {b1['runs']} (B1).")
        elif g["key_rack_short_runs"] < min(f["key_rack_short_runs"], b1["key_rack_short_runs"]):
            out[case] = (f"LeakTrace stopped the leak in {g['leak_stopped']} of {g['runs']} runs with a key rack short in "
                         f"{g['key_rack_short_runs']}; the flat-table rule and B1 left a key rack short in "
                         f"{f['key_rack_short_runs']} and {b1['key_rack_short_runs']}. Its plan needs a person's OK.")
        else:
            out[case] = "See the numbers; no simple summary applies."
    return out


def summarise(rows: list[dict]) -> list[dict]:
    out = []
    for case in CASES:
        for approach in ("graph", "flat", "B1", "B2"):
            rs = [r for r in rows if r["case"] == case and r["approach"] == approach]
            n = len(rs)
            out.append({"case": case, "approach": approach, "runs": n,
                        "leak_stopped": sum(r["leak_stopped"] for r in rs),
                        "key_rack_short_runs": sum(bool(r["key_racks_short"]) for r in rs),
                        "racks_short_avg": round(sum(len(r["racks_short"]) for r in rs) / n, 2),
                        "weighted_shortfall_avg": round(sum(r["weighted_shortfall"] for r in rs) / n, 3),
                        "moves_avg": round(sum(r["moves"] for r in rs) / n, 2),
                        "asked_person": sum(r["asked_person"] for r in rs),
                        "lookups_avg": round(sum(r["lookups"] for r in rs) / n, 1),
                        "max_flow_calls_avg": round(sum(r["max_flow_calls"] for r in rs) / n, 1),
                        "errors": sum(r["errors"] for r in rs)})
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="evaluate")
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--out", default=str(OUT))
    a = p.parse_args(argv)
    t0 = time.time()
    rows = run(a.seeds)
    result = {"ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seconds": round(time.time() - t0, 1),
              "environment": f"{platform.system()} {platform.release()}, Python {platform.python_version()}, "
                             f"FalkorDB at {config.FALKORDB_HOST}:{config.FALKORDB_PORT}",
              "seeds": a.seeds, "cases": {"S1": "leak on the Row A branch pipe", "S5": "small leak on the Rack A2 feed",
                                         "S3": "S1 with the backup link valve V-09 known stuck and really stuck"},
              "approaches": {
                  "graph": "LeakTrace through its API: likely causes, what is affected several links away, every "
                           "plan tested with max flow against its checks, what it remembers, and the auto-mode limits",
                  "flat": "a fixed rule on flat tables, not LeakTrace's checks: close the valves next to the "
                          "suspected section, count only racks fed directly by it, skip a valve with an open "
                          "failed-to-operate ticket; one lookup per table, no paths, no max flow",
                  "B1": "close the nearest valve upstream of the suspected section",
                  "B2": "isolate the whole loop (close every open valve)"},
              "not_run": ["B3: a language model with flat tables (no model key was set)"],
              "scored_by": "our own simulator (scenario_generator/plant.py) on practice data, not real equipment; "
                           "a plan that needs a person's OK is scored as if approved",
              "summary": summarise(rows), "notes": notes(summarise(rows)), "runs": rows}
    Path(a.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
