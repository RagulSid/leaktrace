"""The public "How it works" page: live, read-only, demo customer only.

Rules this module keeps:
  * every number comes from a FalkorDB call made for this request (or from the test results the test run wrote);
  * the query text shown is the saved text from app/graph/queries, byte for byte, with its parameters separate;
  * every search runs through GRAPH.RO_QUERY with a timeout (TenantGraph.read) and at most ROW_CAP rows are
    returned; visitors choose a step, never a query or a parameter;
  * it reads the demo customer only (config.DEMO_TENANT) and never lists graphs;
  * if FalkorDB is unreachable every call answers 503 (the page then shows an error and no numbers).
"""

import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app import config
from app.api.views import RateLimit
from app.graph import client as graph_client
from app.graph import queries
from app.graph.client import TenantGraph, rows

router = APIRouter(prefix="/how-it-works")
ROW_CAP = 20
TIMEOUT_MS = 2000
run_limit = RateLimit(10)


def _limit_runs(request: Request) -> None:
    run_limit(request)  # looked up at call time, so the limit can be changed in one place
CHECKS_FILE = Path(__file__).resolve().parents[1] / "data" / "checks.json"
EVALUATION_FILE = Path(__file__).resolve().parents[1] / "data" / "evaluation.json"


def demo() -> TenantGraph:
    return TenantGraph(config.DEMO_TENANT)


def timed_read(tg: TenantGraph, name: str, params: dict | None = None) -> tuple[list[dict], float]:
    t0 = time.perf_counter()
    out = rows(tg.read(name, params or {}, timeout_ms=TIMEOUT_MS))
    return out, round((time.perf_counter() - t0) * 1000, 2)


@router.get("/summary")
def summary():
    tg = demo()
    _, ping_ms = timed_read(tg, "hiw_ping")
    stats, _ = timed_read(tg, "stats")
    labels, _ = timed_read(tg, "hiw_labels")
    types, _ = timed_read(tg, "hiw_rel_types")
    shape, shape_ms = timed_read(tg, "hiw_shape")
    s = stats[0]
    return {"connected": True, "ping_ms": ping_ms, "nodes": s["nodeCount"], "links": s["relCount"],
            "kinds": len(labels[0]["labels"]), "labels": labels[0]["labels"], "link_types": types[0]["types"],
            "shape": shape[:ROW_CAP], "shape_ms": shape_ms,
            "queries": {"stats": queries.load("stats"), "hiw_labels": queries.load("hiw_labels"),
                        "hiw_shape": queries.load("hiw_shape")}}


def _context(tg: TenantGraph) -> dict | None:
    """Parameters for the six steps, taken from the most recent problem that has a plan. Fixed server-side."""
    latest = rows(tg.read("hiw_latest_problem", {}, timeout_ms=TIMEOUT_MS))
    if not latest:
        return None
    ctx = latest[0]
    pol = rows(tg.read("policy_for_zone", {"zone": None}, timeout_ms=TIMEOUT_MS))
    cmin = pol[0]["policy"]["critical_min_criticality"] if pol else config.DEFAULT_CRITICAL_MIN
    ctx["racks"] = rows(tg.read("hiw_key_racks", {"critical_min": cmin}, timeout_ms=TIMEOUT_MS))[0]["racks"]
    ctx["sources"] = rows(tg.read("sources_all", {}, timeout_ms=TIMEOUT_MS))[0]["ids"]
    return ctx


# key -> (saved query, how to build its parameters from the context)
STEPS = [
    ("report", "hiw_report_links", lambda c: {"code": c["report"]}),
    ("balance", "flow_balance_for_segment", lambda c: {"segment": c["segment"]}),
    ("affected", "q2_trace_impact", lambda c: {"segment": c["segment"]}),
    ("plans", "max_flow", lambda c: {"sources": sorted(c["sources"]), "targets": sorted(c["racks"])[:1],
                                     "cap": "cap_base"}),
    ("authority", "hiw_authority", lambda c: {"decision": c["decision"]}),
    ("remember", "hiw_check_remember", lambda c: {"incident": c["incident"]}),
]
BY_KEY = {k: (q, f) for k, q, f in STEPS}


@router.get("/steps")
def steps():
    tg = demo()
    ctx = _context(tg)
    out = []
    for key, name, params in STEPS:
        p = params(ctx) if ctx else None
        plan = tg.explain(name, p).plan if p is not None else []
        out.append({"key": key, "query_name": name, "query": queries.load(name), "params": p, "plan": plan})
    return {"problem": ctx and {"incident": ctx["incident"], "decision": ctx["decision"], "segment": ctx["segment"]},
            "steps": out}


@router.post("/run/{key}", dependencies=[Depends(_limit_runs)])
def run(key: str):
    if key not in BY_KEY:
        raise HTTPException(404, "no such step")
    tg = demo()
    ctx = _context(tg)
    if ctx is None:
        raise HTTPException(409, "no_problem_yet")
    name, params = BY_KEY[key]
    p = params(ctx)
    result, ms = timed_read(tg, name, p)
    profile = tg.profile_read(name, p).plan  # saved read-only searches only: PROFILE runs the query
    return {"key": key, "query_name": name, "query": queries.load(name), "params": p,
            "rows": json.loads(json.dumps(result[:ROW_CAP], default=str)), "row_count": len(result),
            "capped": len(result) > ROW_CAP, "ms": ms, "profile": profile}


FEATURES = [  # (code, saved query names that use it)
    ("search", None),
    ("reach", {"bfs_reach", "q2_trace_impact"}),
    ("flow_test", {"max_flow"}),
    ("meaning_search", {"chunk_search", "brain_passages"}),
    ("pick_up", {"task_claim", "move_task_claim", "agent_task_claim"}),
    ("read_only", "read"),
]


@router.get("/features")
def features():
    tg = demo()
    log = [e for e in list(graph_client.QUERY_LOG) if e.graph == tg.name]  # this process, demo map only
    out = []
    for code, match in FEATURES:
        if match is None:
            hits = log
        elif match == "read":
            hits = [e for e in log if e.mode == "read"]
        else:
            hits = [e for e in log if e.query in match]
        last = hits[-1] if hits else None
        out.append({"feature": code, "calls": len(hits), "last_ms": round(last.ms, 2) if last else None})
    slow = tg.slowlog()
    return {"features": out, "one_map_per_customer": True, "since": "process start",
            "slowest": [{"when": s[0], "command": s[1], "query": s[2][:300], "ms": float(s[3])} for s in slow[:10]]}


@router.get("/proof")
def proof():
    checks = json.loads(CHECKS_FILE.read_text(encoding="utf-8")) if CHECKS_FILE.exists() else None
    evaluation = json.loads(EVALUATION_FILE.read_text(encoding="utf-8")) if EVALUATION_FILE.exists() else None
    return {"checks": checks, "evaluation": evaluation}
