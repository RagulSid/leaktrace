"""Work orders: jobs for people that come out of a decision, and the field crew's confirmations.

From the committed plan's steps:
  inspect:<zone>      field crew checks the area, cleans up and resets the leak sensor
  migrate:<workload>  the owning team moves the job off a rack that will lose flow
  inform:<workload>   the owning team is told their job will run short
From an escalation (no plan passes): people_decide on the problem's zone, for the operators.
From a request for evidence: inspect on each zone of the problem.

A crew member takes a job, confirms each step, then completes it. Completing can report valves that would
not move; each becomes an active 'stuck' Fact, so later plans avoid that valve.
"""

import json

from app import clock, config, ids
from app import permissions as perm
from app.execution.service import ExecError, Forbidden, NotFound, load
from app.graph.client import TenantGraph, rows

STEPS = {
    "inspect": ["check the area", "clean up the water", "reset the leak sensor"],
    "migrate": ["move the job to another rack"],
    "inform": ["tell the owning team"],
    "people_decide": ["agree a plan with the team"],
}
FIELD_KINDS = ("inspect",)
VIEW_ROLES = perm.VIEWERS + perm.FIELD


def _orders(tg: TenantGraph, decision: str) -> list[dict]:
    st = load(tg, decision)
    d = st["decision"]
    record = json.loads(d["explain_json"])
    zones = sorted({z for z in ([record.get("zone")] + ((record.get("suspect") or {}).get("zones") or [])) if z})
    steps: list[str] = []
    if d["kind"] == "act":
        chosen = next((p for p in record["plans"] if p["id"] == record["chosen"]), None)
        steps = list(chosen["steps"]) if chosen else []
    elif d["kind"] == "escalate":
        steps = [f"people_decide:{z}" for z in zones[:1]]
    elif d["kind"] == "request_evidence":
        steps = [f"inspect:{z}" for z in zones]
    workloads = [s.split(":", 1)[1] for s in steps if s.split(":", 1)[0] in ("migrate", "inform")]
    owners = {r["workload"]: r["owners"] for r in rows(tg.read("workload_owners", {"ids": workloads}))} if workloads else {}
    out = []
    for s in steps:
        kind, _, target = s.partition(":")
        if kind not in STEPS:
            continue
        team = (owners.get(target) or [None])[0] if kind in ("migrate", "inform") else None
        out.append({"id": "WO-" + ids.task_id()[4:], "kind": kind, "target": target, "steps": STEPS[kind], "team": team})
    return out


def create_for_decision(tg: TenantGraph, decision: str, actor: str) -> list[str]:
    """Create the jobs for a decision, once. Returns the new ids (empty if they already exist)."""
    orders = _orders(tg, decision)
    if not orders:
        return []
    return rows(tg.write("work_orders_create", {"decision": decision, "orders": orders, "ts": clock.now(),
                                                "actor": actor}))[0]["ids"]


def list_for(tg: TenantGraph, role: str, incident: str | None = None) -> list[dict]:
    if role not in VIEW_ROLES:
        raise Forbidden("role_not_allowed", role=role, action="list_work_orders")
    kinds = list(FIELD_KINDS) if role in perm.FIELD else None
    return rows(tg.read("work_orders_list", {"incident": incident, "kinds": kinds}))


def _get(tg: TenantGraph, wo: str) -> dict:
    out = rows(tg.read("work_order_get", {"id": wo}))
    if not out:
        raise NotFound("no_such_work_order", work_order=wo)
    return out[0]["work_order"]


def _audit(actor: str, role: str, detail: dict | None = None) -> dict:
    return {"audit": ids.audit_id(), "ts": clock.now(), "seq": clock.next_ns(), "by": actor, "role": role,
            "detail": json.dumps(detail or {}, sort_keys=True)}


def take(tg: TenantGraph, wo: str, actor: str, role: str) -> dict:
    if role not in perm.FIELD:
        raise Forbidden("role_not_allowed", role=role, action="take_work_order")
    w = _get(tg, wo)
    if w["kind"] not in FIELD_KINDS:
        raise Forbidden("not_a_field_job", kind=w["kind"])
    if not rows(tg.write("work_order_take", {"id": wo, **_audit(actor, role)})):
        raise ExecError("not_open", status=w["status"])
    return _get(tg, wo)


def confirm(tg: TenantGraph, wo: str, actor: str, role: str, step: str, note: str | None = None) -> dict:
    """Field confirmation of one step, by the crew member who took the job."""
    if role not in perm.FIELD:
        raise Forbidden("role_not_allowed", role=role, action="confirm_step")
    w = _get(tg, wo)
    if step not in w["steps"]:
        raise ExecError("unknown_step", steps=w["steps"])
    if not rows(tg.write("work_order_confirm", {"id": wo, "step": step, **_audit(actor, role, {"note": note})})):
        raise ExecError("cannot_confirm", status=w["status"], assigned_to=w.get("assigned_to"),
                        confirmed=w.get("confirmed"))
    return _get(tg, wo)


def complete(tg: TenantGraph, wo: str, actor: str, role: str, findings: str | None = None,
             stuck_valves: list[str] | None = None) -> dict:
    if role not in perm.FIELD:
        raise Forbidden("role_not_allowed", role=role, action="complete_work_order")
    w = _get(tg, wo)
    stuck_valves = sorted(set(stuck_valves or []))
    known = {r["id"] for r in rows(tg.read("asset_flags", {"ids": stuck_valves}))} if stuck_valves else set()
    if set(stuck_valves) - known:
        raise ExecError("unknown_valves", valves=sorted(set(stuck_valves) - known))
    if not rows(tg.write("work_order_complete", {"id": wo, "findings": findings,
                                                 **_audit(actor, role, {"findings": findings, "stuck": stuck_valves})})):
        raise ExecError("cannot_complete", status=w["status"], missing=[s for s in w["steps"] if s not in w["confirmed"]])
    for v in stuck_valves:
        tg.write("fact_write", {"about": v, "evidence": wo, "id": ids.fact_id(), "kind": "stuck", "ts": clock.now(),
                                "statement": f"{v} would not move (field crew, job {wo}: {findings or 'no note'})",
                                "confidence": config.STUCK_FACT_CONFIDENCE, "source": "field"})
    return _get(tg, wo)
