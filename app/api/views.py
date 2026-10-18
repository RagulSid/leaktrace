"""Routes behind the six screens. They return codes and numbers from the graph; the web app turns codes into
words (web/src/copy.ts). Staff routes work on the customer in the login token; the public report routes work
on the demo customer only and never return internal ids."""

import json
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import clock, config, ids
from app.agents import investigate
from app.agents import runtime as helpers
from app.api.auth import Principal, require
from app.execution import audit as audit_log
from app.execution import service as execution
from pathlib import Path

from app.graph.client import GraphUnavailable, TenantGraph, rows
from app.intake.reports import UnknownAsset, ingest_report
from app.memory import episodic
from app.permissions import FIELD, VIEWERS

router = APIRouter()
MANAGERS = ("manager",)
PACK = Path(__file__).resolve().parents[2] / "packs" / "datacenter" / "topology.json"


# ---------------------------------------------------------------- simple per-visitor rate limit (public routes)

class RateLimit:
    def __init__(self, per_minute: int):
        self.per_minute, self.hits, self.lock = per_minute, defaultdict(deque), threading.Lock()

    def __call__(self, request: Request) -> None:
        key, now = (request.client.host if request.client else "?"), time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                raise HTTPException(429, "too many requests, try again in a minute")
            q.append(now)


public_limit = RateLimit(20)


def _limit_public(request: Request) -> None:
    public_limit(request)  # looked up at call time


def demo_graph() -> TenantGraph:
    return TenantGraph(config.DEMO_TENANT)


# ---------------------------------------------------------------- public: report a problem, track it

KINDS = {"water": "Water where it should not be", "no_water": "No or low water", "flooding": "Flooding",
         "blocked": "Blocked drain", "other": "Something else"}
SEVERITIES = ("small", "spreading", "dangerous")


class PublicReportIn(BaseModel):
    kinds: list[str] = Field(min_length=1, max_length=5)
    where: str = Field(min_length=2, max_length=300)
    severity: str = "small"
    asset_code: str | None = Field(default=None, max_length=40)


PUBLIC_ACCOUNTS = ["operator1", "tech1", "staff1", "safety1"]


@router.get("/public/info")
def public_info():
    """What the public screens need: which customer the demo is (the login form sends it back) and, for judges,
    the practice accounts with the shared practice password (public by design; practice data only). The manager
    password is never sent."""
    shown = config.DEMO_PASSWORD if config.SHOW_PRACTICE_PASSWORD else None
    return {"demo_tenant": config.DEMO_TENANT, "practice": True,
            "practice_sign_in": {"accounts": PUBLIC_ACCOUNTS, "password": shown} if shown else None}


# ---------------------------------------------------------------- reset the practice data (manager only)

_reset_lock = threading.Lock()
_reset_state = {"running": False, "last": None}


def _run_reset(tenant: str) -> None:
    from app.cli import Refused, ensure_demo, reset_graph

    try:
        reset_graph(TenantGraph(tenant))
        out = ensure_demo(tenant, str(PACK))
        _reset_state["last"] = {"ok": True, "at": clock.now(), "story": out.get("story")}
    except (Refused, GraphUnavailable) as e:
        _reset_state["last"] = {"ok": False, "at": clock.now(), "error": type(e).__name__}
    finally:
        _reset_state["running"] = False
        _reset_lock.release()


@router.post("/practice/reset", status_code=202)
def practice_reset(p: Principal = Depends(require(*MANAGERS))):
    """Wipe the demo customer's practice data and build it again (ensure-demo), in the background. Only for the
    demo customer; one reset at a time. Until it is done the screens show "waking up"."""
    if p.tenant != config.DEMO_TENANT:
        raise HTTPException(403, "only the demo customer's practice data can be reset")
    if not _reset_lock.acquire(blocking=False):
        raise HTTPException(409, "a reset is already running")
    _reset_state["running"] = True
    threading.Thread(target=_run_reset, args=(p.tenant,), daemon=True).start()
    return {"status": "resetting"}


@router.get("/practice/reset")
def practice_reset_status(p: Principal = Depends(require(*MANAGERS))):
    return dict(_reset_state)


@router.post("/public/reports", dependencies=[Depends(_limit_public)])
def public_report(body: PublicReportIn):
    if any(k not in KINDS for k in body.kinds) or body.severity not in SEVERITIES:
        raise HTTPException(422, "unknown choice")
    text = f"{', '.join(KINDS[k] for k in body.kinds)}. Where: {body.where}. Looks {body.severity}."
    try:
        out = ingest_report(demo_graph(), text=text, reporter="public-" + ids.report_code()[2:].lower(),
                            asset_code=body.asset_code or None, hazard=body.severity == "dangerous",
                            source="synthetic")
    except UnknownAsset:
        raise HTTPException(422, "unknown_asset_code")
    return {"code": out["code"]}  # nothing internal goes back to the public


def _stages(s: dict) -> list[dict]:
    done = {"received": True, "located": s["linked"] > 0, "checked": s["decisions"] > 0,
            "crew": s["running"] > 0 or s["crew_on_site"] > 0, "fixed": s["problem_status"] in ("resolved", "closed")}
    order = ["received", "located", "checked", "crew", "fixed"]
    if done["fixed"]:
        done.update(crew=True, checked=True)
    current = next((k for k in order if not done[k]), None)
    return [{"key": k, "done": done[k], "current": k == current} for k in order]


@router.get("/public/reports/{code}", dependencies=[Depends(_limit_public)])
def public_report_status(code: str):
    out = rows(demo_graph().read("public_report_status", {"code": code}))
    if not out:
        raise HTTPException(404, "no_such_report")
    s = out[0]
    return {"code": s["code"], "sent_at": s["sent_at"], "stages": _stages(s), "others": max(0, (s["reports"] or 1) - 1),
            "can_confirm": s["problem_status"] == "open", "notice": None}


@router.post("/public/reports/{code}/confirm", dependencies=[Depends(_limit_public)])
def public_report_confirm(code: str):
    out = rows(demo_graph().write("report_confirm", {
        "code": code, "id": ids.report_id(), "new_code": ids.report_code(), "ts": clock.now(),
        "reporter": "public-" + ids.report_code()[2:].lower(), "source": "synthetic"}))
    if not out:
        raise HTTPException(409, "problem_not_open")
    return {"code": out[0]["code"]}


# ---------------------------------------------------------------- open problems

@router.get("/problems")
def problems(p: Principal = Depends(require(*VIEWERS))):
    return rows(p.graph().read("incidents_queue"))


def latest_decision(tg: TenantGraph, incident: str) -> str | None:
    out = rows(tg.read("incidents_queue_one", {"id": incident}))
    return out[0]["decision"] if out else None


@router.get("/problems/{incident}")
def problem(incident: str, p: Principal = Depends(require(*VIEWERS))):
    tg = p.graph()
    inc = rows(tg.read("incident_get", {"id": incident}))
    if not inc:
        raise HTTPException(404, "no such problem")
    did = latest_decision(tg, incident)
    record = investigate.get_decision(tg, did) if did else None
    return {"incident": inc[0], "decision": record, "status": execution.status(tg, did) if did else None,
            "chain": helpers.chain(tg, incident), "reports": inc[0]["reports"]}


@router.get("/problems/{incident}/map")
def problem_map(incident: str, p: Principal = Depends(require(*VIEWERS))):
    """The flow network with what to highlight for this problem: the "why we think so" path, the suspected
    section, what is affected and the valves the chosen plan moves."""
    tg = p.graph()
    if not rows(tg.read("incident_get", {"id": incident})):
        raise HTTPException(404, "no such problem")
    did = latest_decision(tg, incident)
    rec = investigate.get_decision(tg, did) if did else None
    path: list[str] = []
    for line in (rec or {}).get("evidence_paths") or []:
        path += [x.strip() for x in line.split("->")]
    chosen = next((pl for pl in (rec or {}).get("plans") or [] if pl["id"] == (rec or {}).get("chosen")), None)
    return {"nodes": rows(tg.read("map_nodes")), "edges": rows(tg.read("map_edges")),
            "sensors": rows(tg.read("map_sensors")),
            "highlight": {"path": sorted(set(path)), "suspect": ((rec or {}).get("suspect") or {}).get("segment"),
                          "affected": [d["consumer"] for d in ((rec or {}).get("impact") or {}).get("downstream", [])],
                          "plan_valves": [op.split(":", 1)[1] for op in (chosen or {}).get("ops", [])]}}


@router.get("/problems/{incident}/timeline")
def problem_timeline(incident: str, p: Principal = Depends(require(*VIEWERS))):
    """Who did what: the hand-off chain (Task nodes) and every step, with the chooser recorded on it."""
    tg = p.graph()
    if not rows(tg.read("incident_get", {"id": incident})):
        raise HTTPException(404, "no such problem")
    return {"chain": helpers.chain(tg, incident), "steps": episodic.for_incident(tg, incident)}


# ---------------------------------------------------------------- auto mode settings and review

EDITABLE = {  # name -> (min, max, type)
    "min_confidence": (0.5, 1.0, float), "max_auto_criticality": (0, 5, int), "max_auto_operations": (0, 10, int),
    "rate_limit_per_zone_per_hour": (0, 100, int), "break_glass_wait_s": (30, 3600, int),
    "verify_window_s": (30, 3600, int), "min_playbook_successes": (1, 20, int), "auto_promotion_ceiling": (0, 5, int),
}


@router.get("/policies")
def policies(p: Principal = Depends(require(*VIEWERS))):
    tg = p.graph()
    out = []
    for r in rows(tg.read("policies_list")):
        pol = dict(r["policy"])
        hist = rows(tg.read("policy_history", {"id": pol["id"]}))
        for h in hist:
            h["detail"] = json.loads(h.pop("detail_json") or "{}")
        out.append({"policy": pol, "history": hist, "editable": sorted(EDITABLE)})
    return out


class PolicyIn(BaseModel):
    changes: dict


class FreezeIn(BaseModel):
    paused: bool


def _policy_write(p: Principal, pid: str, props: dict, reason: str) -> dict:
    tg = p.graph()
    before = next((dict(r["policy"]) for r in rows(tg.read("policies_list")) if r["policy"]["id"] == pid), None)
    if before is None:
        raise HTTPException(404, "no such policy")
    detail = {k: {"from": before.get(k), "to": v} for k, v in props.items()}
    out = rows(tg.write("policy_update", {
        "id": pid, "props": props, "ts": clock.now(), "seq": clock.next_ns(), "by": p.user, "role": p.role,
        "audit": ids.audit_id(), "before": json.dumps({k: before.get(k) for k in props}, sort_keys=True),
        "after": json.dumps(props, sort_keys=True), "reason": reason, "detail": json.dumps(detail, sort_keys=True)}))
    return dict(out[0]["policy"])


@router.put("/policies/{pid}")
def policy_update(pid: str, body: PolicyIn, p: Principal = Depends(require(*MANAGERS))):
    props = {}
    for k, v in body.changes.items():
        if k not in EDITABLE:
            raise HTTPException(422, f"not_editable:{k}")
        lo, hi, typ = EDITABLE[k]
        try:
            v = typ(v)
        except (TypeError, ValueError):
            raise HTTPException(422, f"bad_value:{k}")
        if not lo <= v <= hi:
            raise HTTPException(422, f"out_of_range:{k}")
        props[k] = v
    if not props:
        raise HTTPException(422, "nothing_to_change")
    return _policy_write(p, pid, props, "settings_changed")


@router.post("/policies/{pid}/pause")
def policy_pause(pid: str, body: FreezeIn, p: Principal = Depends(require(*MANAGERS))):
    return _policy_write(p, pid, {"frozen": body.paused}, "auto_mode_paused" if body.paused else "auto_mode_resumed")


@router.get("/review")
def review(p: Principal = Depends(require(*VIEWERS))):
    tg = p.graph()
    return {"on_their_own": rows(tg.read("actions_on_own")), "reviews": rows(tg.read("reviews_list")),
            "knowledge": rows(tg.read("brain_reviews_open"))}


@router.post("/reviews/{rid}/resolve")
def review_resolve(rid: str, p: Principal = Depends(require(*MANAGERS))):
    if not rows(p.graph().write("review_resolve", {"id": rid, "by": p.user, "ts": clock.now()})):
        raise HTTPException(409, "not_open")
    return {"id": rid, "status": "resolved"}


@router.get("/learned")
def learned(p: Principal = Depends(require(*VIEWERS))):
    tg = p.graph()
    facts, books = rows(tg.read("facts_list")), rows(tg.read("playbooks_list"))
    wanted = {f["about"] for f in facts} | {b["segment"] for b in books}
    wanted |= {s.split(":", 1)[1] for b in books for s in b["steps"] or [] if ":" in s}
    names = {r["id"]: r["name"] for r in rows(tg.read("entity_names", {"ids": sorted(x for x in wanted if x)}))}
    return {"facts": facts, "playbooks": books, "names": names}


@router.post("/facts/{fid}/{action}")
def fact_action(fid: str, action: str, p: Principal = Depends(require(*MANAGERS))):
    if action not in ("confirm", "retire"):
        raise HTTPException(404, "unknown action")
    tg = p.graph()
    out = rows(tg.write("fact_set_status", {"id": fid, "status": "active" if action == "confirm" else "retired",
                                            "ts": clock.now(), "by": p.user}))
    if not out:
        if rows(tg.read("brain_facts", {"about": [], "ids": [fid]})):
            raise HTTPException(409, "replaced_by_a_newer_fact")
        raise HTTPException(404, "no such fact")
    return out[0]


# ---------------------------------------------------------------- field crew

@router.get("/crew/steps")
def crew_steps(p: Principal = Depends(require(*FIELD))):
    """Valve moves waiting for the field crew (and the ones this person holds)."""
    return rows(p.graph().read("crew_valve_steps", {"user": p.user}))


@router.get("/whoami")
def whoami(p: Principal = Depends(require("staff", "operator", "tech", "manager", "authority", "integration"))):
    return {"user": p.user, "role": p.role, "tenant": p.tenant}


# keep audit_log imported for policy history readers
_ = audit_log
