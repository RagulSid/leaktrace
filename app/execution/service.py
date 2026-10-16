"""Carrying out a committed decision: approval, execution through the actuator, verification and undo.

The lifecycle is in app/domain/lifecycle.py. Every transition is one conditional write on the Decision (it
only applies while the status is still the expected one) together with its AuditEvent, so a transition is
either fully recorded or not at all, and two callers can never both make it. A FalkorDB query that fails
part-way applies none of its writes (checked by running it), so no step is ever half-applied.

Who may do what is checked here, so the API and the CLI apply the same rules. The tenant is whatever graph
the caller hands in; callers bind it from the login token (API) or the operator's shell (CLI).

Time-based changes (leases running out, approvals expiring, verification windows closing) are applied
lazily by sweep(), which every entry point runs first.
"""

import json

from app import clock, config, ids
from app import permissions as perm
from app.actuation.adapter import ACTUATOR, Move, make_before_break
from app.agents import investigate as investigation
from app.domain import confidence as conf
from app.domain import breakglass, fingerprint, lifecycle
from app.domain import verification as verif
from app.actuation import notify
from app.execution import audit as audit_log
from app.graph.client import TenantGraph, rows

SYSTEM = perm.SYSTEM
AUTO = "auto"  # actor name for auto mode
CHECKER = "checker"  # actor name for automatic verification
BREAK_GLASS = "break_glass"  # actor name for the emergency path (BUILD_PROMPT §5)
AGENT_TASK_KINDS = ("triage", "investigate", "plan", "dispatch", "verify", "record")


class ExecError(Exception):
    status = 409

    def __init__(self, code: str, **detail):
        super().__init__(code)
        self.code, self.detail = code, detail


class NotFound(ExecError):
    status = 404


class Forbidden(ExecError):
    status = 403


class BadRequest(ExecError):
    status = 422


def _require(role: str, allowed: tuple, action: str) -> None:
    if role not in allowed:
        raise Forbidden("role_not_allowed", role=role, action=action)


def _audit(actor: str, role: str, reason: str, detail: dict | None = None) -> dict:
    return {"audit": ids.audit_id(), "ts": clock.now(), "seq": clock.next_ns(), "actor": actor, "role": role,
            "reason": reason, "detail": json.dumps(detail or {}, sort_keys=True, default=str)}


# ---------------------------------------------------------------- reading state


def load(tg: TenantGraph, decision: str) -> dict:
    out = rows(tg.read("decision_state", {"id": decision}))
    if not out:
        raise NotFound("no_such_decision", decision=decision)
    r = out[0]
    chosen = [c for c in r["chosen"] if c.get("id")]
    return {"decision": r["decision"], "incident": r["incident"], "chosen": chosen[0] if chosen else None,
            "approval": (r["approvals"] or [None])[0], "execution": (r["executions"] or [None])[0],
            "verifications": sorted(r["verifications"], key=lambda v: v["ts"])}


def _illegal(tg: TenantGraph, decision: str, to: str) -> ExecError:
    return ExecError("illegal_transition", status=load(tg, decision)["decision"]["status"], to=to)


def transition(tg: TenantGraph, decision: str, frm: list[str], to: str, actor: str, role: str, reason: str,
               detail: dict | None = None) -> str:
    for f in frm:
        lifecycle.check(f, to)
    out = rows(tg.write("decision_transition", {"id": decision, "from": list(frm), "to": to,
                                                **_audit(actor, role, reason, detail)}))
    if not out:
        raise _illegal(tg, decision, to)
    return out[0]["prev"]


def _supersede(tg: TenantGraph, decision: str, actor: str, role: str, reason: str, detail: dict) -> None:
    transition(tg, decision, list(lifecycle.OPEN), "superseded", actor, role, reason, detail)
    tg.write("approval_withdraw", {"id": decision, "status": "withdrawn"})


def status(tg: TenantGraph, decision: str, *, do_sweep: bool = True) -> dict:
    if do_sweep:
        sweep(tg)
    st = load(tg, decision)
    d, x, ap = st["decision"], st["execution"], st["approval"]
    tasks = rows(tg.read("execution_tasks", {"execution": x["id"]})) if x else []
    ver = st["verifications"][-1] if st["verifications"] else None
    return {
        "decision": decision, "incident": st["incident"], "kind": d["kind"], "status": d["status"],
        "outcome": d.get("outcome"), "authority_level": d["authority_level"],
        "failed_conditions": d.get("failed_conditions") or [], "requested_by": d.get("requested_by"),
        "fingerprint": d.get("fingerprint"), "plan": st["chosen"],
        "approval": {k: ap.get(k) for k in ("id", "by", "role", "ts", "expires_at")} if ap else None,
        "execution": {k: x.get(k) for k in ("id", "started_at", "started_by", "adapter", "simulated", "authorized_by",
                                            "verifying_since", "verify_window_s")} if x else None,
        "tasks": [{k: t[k] for k in ("id", "phase", "seq", "valve", "target", "prior_state", "status", "owner",
                                     "attempts", "failure", "observed")} for t in tasks],
        "actions": rows(tg.read("actions_for_decision", {"id": decision})),
        "verification": {"id": ver["id"], "ts": ver["ts"], "passed": ver["passed"], "failed_checks": ver["failed_checks"],
                         "checks": json.loads(ver["checks_json"])} if ver else None,
        "next": lifecycle.next_actions(d["status"], d["authority_level"]),
    }


def audit(tg: TenantGraph, decision: str) -> list[dict]:
    load(tg, decision)  # 404 if missing
    out = rows(tg.read("audit_for_decision", {"id": decision}))
    for r in out:
        r["detail"] = json.loads(r.pop("detail_json") or "{}")
    return out


# ---------------------------------------------------------------- time-based changes


def sweep(tg: TenantGraph, now: float | None = None) -> dict:
    """Apply what time has decided: expired leases (back to open, or abandoned after the last attempt, which
    fails the execution), expired approvals (back to proposed), and verification windows that closed
    without fresh readings (failed)."""
    now = clock.now() if now is None else now
    released = rows(tg.write("move_tasks_release_expired", {"now": now, "max_attempts": config.MOVE_MAX_ATTEMPTS,
                                                           "seq": clock.next_ns()}))
    aborted = []
    for r in released:
        if r["status"] != "abandoned":
            continue
        phase_status, final = (("executing", "failed") if r["phase"] == "forward"
                               else ("rolling_back", "rollback_failed"))
        if rows(tg.write("execution_abort", {"decision": r["decision"], "phase_status": phase_status, "final_status": final,
                                             **_audit(SYSTEM, SYSTEM, f"worker_lost: {r['task']}", {"task": r["task"]})})):
            aborted.append(r["decision"])
    expired = []
    for r in rows(tg.read("approvals_expired", {"now": now})):
        if rows(tg.write("approval_expire", {"approval": r["approval"], "now": now,
                                             **_audit(SYSTEM, SYSTEM, "approval_expired", {"approval": r["approval"]})})):
            expired.append(r["decision"])
    timed_out = []
    for r in rows(tg.read("decisions_verifying")):
        window = r["window"] or config.VERIFY_WINDOW_S
        if r["since"] is not None and now > r["since"] + window:
            verify(tg, r["decision"], CHECKER, SYSTEM, wait_ok=False, do_sweep=False)
            timed_out.append(r["decision"])
    glass = _break_glass(tg, now)
    agent_released = rows(tg.write("agent_tasks_release_expired", {"now": now, "kinds": list(AGENT_TASK_KINDS)}))[0]["ids"]
    woken = rows(tg.write("agent_tasks_wake", {"now": now}))[0]["ids"]
    return {"released": [r["task"] for r in released], "aborted": aborted, "approvals_expired": expired,
            "verification_timeouts": timed_out, "break_glass": glass, "helper_steps_released": agent_released,
            "helper_steps_woken": woken}


def _break_glass(tg: TenantGraph, now: float) -> list[dict]:
    """Emergency path (BUILD_PROMPT §5): a plan that needs a person's OK, with a leak alarm and live
    equipment near the water, waiting longer than the policy's break_glass_wait_s. The minimal isolating plan
    runs only if it passes conditions 1, 2, 3, 5, 7 and 8 (app/domain/breakglass.py) and is the committed
    plan; it still goes through the stale-decision guard. Either way a review item is queued and people are
    notified. Each decision is looked at once."""
    out = []
    for c in rows(tg.read("break_glass_candidates")):
        did = c["decision"]
        st = load(tg, did)
        d = st["decision"]
        record = json.loads(d["explain_json"])
        if breakglass.trigger(record) is None:
            tg.write("decision_mark_break_glass", {"id": did, "result": "not_applicable"})
            continue
        policy = _live_policy(tg, d.get("zone"))
        if not breakglass.due(policy, d["ts"], now):
            continue
        verdict = breakglass.check(record, policy)
        tg.write("decision_mark_break_glass", {"id": did, "result": "execute" if verdict["execute"] else "refused"})
        if verdict["execute"]:
            try:
                approve(tg, did, BREAK_GLASS, SYSTEM, break_glass=True)
                execute(tg, did, BREAK_GLASS, SYSTEM)
            except ExecError as e:
                verdict = {**verdict, "execute": False, "refused_by": e.code, "detail": e.detail}
        kind = "break_glass" if verdict["execute"] else "escalation"
        audit_log.write(tg, did, kind="break_glass", actor=BREAK_GLASS, role=SYSTEM, frm="L3",
                    to="executed" if verdict["execute"] else "refused",
                    reason="break_glass" if verdict["execute"] else "break_glass_refused", detail=verdict)
        tg.write("review_write", {"decision": did, "id": "REV-" + ids.audit_id()[4:], "kind": kind, "ts": now,
                                  "reason": ", ".join(verdict["failed"]) or "executed without approval",
                                  "detail": json.dumps(verdict, sort_keys=True, default=str)})
        notify.send(tg, c["incident"], to=["operator", "manager"],
                    code="break_glass_executed" if verdict["execute"] else "break_glass_refused",
                    message=(f"Emergency action taken on {did}: needs review" if verdict["execute"]
                             else f"Emergency action refused on {did}: people must decide now"))
        out.append({"decision": did, **verdict})
    return out


# ---------------------------------------------------------------- propose


def investigate(tg: TenantGraph, incident: str, requested_by: str, role: str, *, auto: bool = True,
                previous: str | None = None, cap: dict | None = None) -> dict:
    """Investigate and commit a decision. Older open decisions on the same problem are superseded. An L2
    decision is executed straight away if auto mode is on (it is re-checked at that moment)."""
    if role != SYSTEM:
        _require(role, perm.DECIDERS, "investigate")
    if not rows(tg.read("incident_get", {"id": incident})):
        raise NotFound("no_such_problem", incident=incident)
    sweep(tg)
    live = rows(tg.read("decisions_for_incident", {"incident": incident, "statuses": list(lifecycle.IN_PROGRESS)}))
    if live:
        raise ExecError("execution_in_progress", decision=live[0]["id"], status=live[0]["status"])
    rec = investigation.run(tg, incident, actor="planner", requested_by=requested_by, cap=cap)
    new = rec["decision_id"]
    for o in rows(tg.read("decisions_for_incident", {"incident": incident, "statuses": list(lifecycle.OPEN)})):
        if o["id"] != new:
            _supersede(tg, o["id"], "planner", SYSTEM, "newer_decision", {"by": new})
    if previous:
        tg.write("decision_supersedes", {"new": new, "old": previous})
    rec["status"] = "proposed" if rec["kind"] == "act" else "recorded"
    return after_commit(tg, rec, auto=auto)


def after_commit(tg: TenantGraph, rec: dict, *, auto: bool = True) -> dict:
    """An L2 decision runs straight away when auto mode is on (checked again at that moment)."""
    new = rec["decision_id"]
    if auto and rec["kind"] == "act" and rec["authority"]["level"] == "L2":
        try:
            rec["execution"] = execute(tg, new, AUTO, SYSTEM)
        except ExecError as e:
            rec["execution"] = {"error": e.code, **e.detail}
    return rec


def _live_policy(tg: TenantGraph, zone: str | None) -> dict | None:
    out = rows(tg.read("policy_for_zone", {"zone": zone}))
    return out[0]["policy"] if out else None


# ---------------------------------------------------------------- approve / reject


def approve(tg: TenantGraph, decision: str, actor: str, role: str, ttl_s: int | None = None,
            note: str | None = None, *, break_glass: bool = False) -> dict:
    system = role == SYSTEM
    if not system:
        _require(role, perm.APPROVERS, "approve")
    sweep(tg)
    d = load(tg, decision)["decision"]
    if d["kind"] != "act":
        raise ExecError("nothing_to_approve", kind=d["kind"])
    if d["authority_level"] == "L4":
        raise ExecError("people_decide", authority_level="L4")
    if system and d["authority_level"] != "L2" and not (break_glass and d["authority_level"] == "L3"):
        raise Forbidden("auto_approval_needs_l2", authority_level=d["authority_level"])
    if not system and actor == d.get("requested_by"):
        raise Forbidden("self_approval", requested_by=actor)
    if d["status"] != "proposed":
        raise ExecError("illegal_transition", status=d["status"], to="approved")
    ttl = config.APPROVAL_TTL_S if ttl_s is None else int(ttl_s)
    if not 1 <= ttl <= config.APPROVAL_TTL_S:
        raise BadRequest("bad_ttl", allowed=[1, config.APPROVAL_TTL_S])
    p = _audit(actor, role, "break_glass" if break_glass else "auto_mode" if system else "approved",
               {"authority_level": d["authority_level"], "note": note, "ttl_s": ttl})
    out = rows(tg.write("approval_write", {"id": decision, "approval": ids.approval_id(), "by": actor,
                                           "expires_at": p["ts"] + ttl, "ttl_s": ttl, "note": note, **p}))
    if not out:
        raise _illegal(tg, decision, "approved")
    return status(tg, decision, do_sweep=False)


def reject(tg: TenantGraph, decision: str, actor: str, role: str, reason: str | None = None) -> dict:
    _require(role, perm.APPROVERS, "reject")
    sweep(tg)
    load(tg, decision)
    transition(tg, decision, list(lifecycle.OPEN), "rejected", actor, role, reason or "rejected")
    tg.write("approval_withdraw", {"id": decision, "status": "withdrawn"})
    return status(tg, decision, do_sweep=False)


# ---------------------------------------------------------------- execute


def _moves(tg: TenantGraph, ops: list[str], snapshot: dict) -> tuple[list[Move], dict]:
    states = {v[0]: v[1] for v in snapshot["valves"]}
    edges = rows(tg.read("flow_edges_all"))
    moves, prior = [], {}
    for valve, target in make_before_break(ops):
        mine = sorted((e for e in edges if e["valve_id"] == valve), key=lambda e: e["id"])
        prior[valve] = {"state": states[valve], "edges": {e["id"]: e["cap_base"] for e in mine}}
        caps = tuple(0 if target == "closed" else e["open_cap"] for e in mine)
        moves.append(Move(valve, target, states[valve], tuple(e["id"] for e in mine), caps))
    return moves, prior


def _expected(record: dict) -> dict:
    chosen = next(p for p in record["plans"] if p["id"] == record["chosen"])
    crit = next(c for c in chosen["checks"] if c["code"] == "critical_supplied")["detail"]["consumers"]
    v = record.get("verification") or {}
    return {
        "leak_segment": record["suspect"]["segment"],
        "isolation_meters": v.get("isolation_meters") or [],
        "critical": {cid: {"meters": (v.get("critical_meters") or {}).get(cid, []),
                           "expected": min(x["flow"], x["required"])} for cid, x in crit.items()},
        "pressure_sensors": record["suspect"]["signals"]["pressure_anomalies"],
    }


def execute(tg: TenantGraph, decision: str, actor: str, role: str) -> dict:
    system = role == SYSTEM
    if not system:
        _require(role, perm.DECIDERS, "execute")
    if decision in sweep(tg)["approvals_expired"]:
        raise ExecError("approval_expired", status="proposed")
    st = load(tg, decision)
    d = st["decision"]
    if d["kind"] != "act" or not st["chosen"]:
        raise ExecError("nothing_to_execute", kind=d["kind"])
    if d["authority_level"] == "L4":
        raise ExecError("people_decide", authority_level="L4")

    if d["status"] == "proposed":
        if d["authority_level"] != "L2":
            raise ExecError("needs_approval", authority_level=d["authority_level"],
                            failed_conditions=d.get("failed_conditions") or [])
        policy = _live_policy(tg, d.get("zone"))  # auto mode is checked now, not when the plan was made
        if policy is None or policy.get("frozen"):
            reason = "auto_mode_paused" if policy else "no_active_policy"
            tg.write("authority_downgrade", {"id": decision, "condition": "policy_active",
                                             **_audit(actor, role, reason, {"policy": policy and policy["id"]})})
            raise ExecError("needs_approval", authority_level="L3", reason=reason)
        approve(tg, decision, AUTO, SYSTEM)
        st = load(tg, decision)
        d = st["decision"]

    if d["status"] != "approved":
        raise ExecError("illegal_transition", status=d["status"], to="executing")
    ap = st["approval"]
    if ap is None or ap["expires_at"] < clock.now():
        sweep(tg)
        raise ExecError("approval_expired", approval=ap and ap["id"])

    # stale-decision guard: the plan must still fit the graph it was computed on
    snap = rows(tg.read("world_snapshot"))[0]
    changes = fingerprint.material_changes(json.loads(d["snapshot_json"]), snap)
    if changes:
        _supersede(tg, decision, actor, role, "stale_decision", {"changes": changes})
        new = investigate(tg, st["incident"], d.get("requested_by") or actor, SYSTEM, auto=False, previous=decision)
        raise ExecError("stale_decision", changes=changes, new_decision=new["decision_id"], new_kind=new["kind"],
                        new_summary=new["summary"], new_authority=new["authority"]["level"])

    moves, prior = _moves(tg, st["chosen"]["ops"], snap)
    if not moves:
        raise ExecError("nothing_to_execute", kind=d["kind"])
    record = json.loads(d["explain_json"])
    policy = _live_policy(tg, d.get("zone"))
    xid = ids.execution_id()
    out = rows(tg.write("execution_start", {
        "decision": decision, "valve_ids": [m.valve for m in moves], "prior": {v: p["state"] for v, p in prior.items()},
        "execution": xid, "zone": d.get("zone"), "adapter": ACTUATOR.name, "simulated": ACTUATOR.simulated,
        "authorized_by": d["policy"] if ap["by"] in (AUTO, BREAK_GLASS) else ap["id"],
        "prior_json": json.dumps(prior, sort_keys=True), "expected_json": json.dumps(_expected(record), sort_keys=True),
        "verify_window_s": (policy or {}).get("verify_window_s") or config.VERIFY_WINDOW_S,
        "tasks": ACTUATOR.commands(xid, "forward", moves),
        **_audit(actor, role, "execute", {"execution": xid, "order": [f"{m.target}:{m.valve}" for m in moves],
                                          "fingerprint": d.get("fingerprint")}),
    }))
    if not out:  # status or a valve changed between the checks above and the write
        raise ExecError("changed_during_execute", status=load(tg, decision)["decision"]["status"])
    return status(tg, decision, do_sweep=False)


# ---------------------------------------------------------------- field workers


def claim(tg: TenantGraph, worker: str, role: str, lease_s: int | None = None) -> dict | None:
    _require(role, perm.FIELD, "claim")
    lease = config.DEFAULT_LEASE_S if lease_s is None else int(lease_s)
    if not 1 <= lease <= config.MAX_LEASE_S:
        raise BadRequest("bad_lease", allowed=[1, config.MAX_LEASE_S])
    sweep(tg)
    now = clock.now()
    out = rows(tg.write("move_task_claim", {"worker": worker, "role": role, "until": now + lease, "ts": now,
                                            "max_attempts": config.MOVE_MAX_ATTEMPTS, "seq": clock.next_ns(),
                                            "audit": ids.audit_id()}))
    return out[0] if out else None


def report(tg: TenantGraph, task: str, worker: str, role: str, key: str, outcome: str, observed: str | None,
           reason: str | None = None) -> dict:
    """A worker reports a valve move. Reporting the same result again (same idempotency key) returns the
    recorded result and changes nothing."""
    _require(role, perm.FIELD, "report")
    if outcome not in ("done", "failed"):
        raise BadRequest("bad_outcome", allowed=["done", "failed"])
    found = rows(tg.read("move_task_get", {"id": task}))
    if not found:
        raise NotFound("no_such_task", task=task)
    t, decision = found[0]["task"], found[0]["decision"]
    if t["idem_key"] != key:
        raise ExecError("wrong_idempotency_key", task=task)
    if t["status"] in ("done", "failed"):
        return {"duplicate": True, "task": task, "task_status": t["status"], **status(tg, decision, do_sweep=False)}
    if t["status"] != "claimed" or t.get("owner") != worker:
        raise ExecError("lease_lost", task=task, task_status=t["status"])

    result, why = ACTUATOR.outcome(t["target"], outcome, observed, reason)
    forward = t["phase"] == "forward"
    base = {"task": task, "worker": worker, "role": role, "key": key, "observed": observed,
            "phase_status": "executing" if forward else "rolling_back", "ts": clock.now(),
            "seq": clock.next_ns(), "seq2": clock.next_ns(), "audit_task": ids.audit_id(), "audit_decision": ids.audit_id(),
            "detail": json.dumps({"reported": outcome, "observed": observed, "reason": reason}, sort_keys=True)}
    if result == "done":
        out = rows(tg.write("move_done", {**base, "action": ids.action_id(),
                                          "final_status": "verifying" if forward else "rolled_back",
                                          "final_reason": "all_moves_done" if forward else "undo_complete"}))
    else:
        out = rows(tg.write("move_failed", {
            **base, "reason": why, "final_status": "failed" if forward else "rollback_failed", "fact": ids.fact_id(),
            "statement": f"{t['valve']} did not move to {t['target']} when commanded (field report on {task})",
            "fact_confidence": config.STUCK_FACT_CONFIDENCE}))
    if not out:
        raise ExecError("lease_lost", task=task)
    if result == "done" and out[0]["status"] == "rolled_back":
        _after_undo(tg, decision)
    return {"duplicate": False, "task": task, "result": result, "reason": why, **status(tg, decision, do_sweep=False)}


# ---------------------------------------------------------------- verify


def verify(tg: TenantGraph, decision: str, actor: str, role: str, *, wait_ok: bool = True, do_sweep: bool = True) -> dict:
    """Check fresh readings against the plan's expected result. While some reading is not fresh yet and the
    window is still open, nothing changes and the answer says what it is waiting for."""
    system = role == SYSTEM
    if not system:
        _require(role, perm.DECIDERS, "verify")
    if do_sweep:
        sweep(tg)
    st = load(tg, decision)
    d, x = st["decision"], st["execution"]
    if d["status"] != "verifying":
        raise ExecError("illegal_transition", status=d["status"], to="verified")
    expected = json.loads(x["expected_json"])
    balance = conf.balance_view(rows(tg.read("flow_balance_for_segment", {"segment": expected["leak_segment"]})))
    needed = verif.instruments(expected, balance)
    readings = {r["id"]: r for r in rows(tg.read("instruments_current", {"ids": needed}))}
    since = x["verifying_since"]
    checks, stale = verif.evaluate(expected, readings, balance, since)
    window = x.get("verify_window_s") or config.VERIFY_WINDOW_S
    if stale and wait_ok and clock.now() <= since + window:
        return {**status(tg, decision, do_sweep=False), "waiting_for": stale, "verify_by": since + window}

    passed = all(c.passed for c in checks)
    failed = [c.code for c in checks if not c.passed]
    to = "verified" if passed else "failed"
    out = rows(tg.write("verification_write", {
        "decision": decision, "to": to, "verification": ids.verification_id(), "passed": passed, "failed": failed,
        "checks_json": json.dumps([c.__dict__ for c in checks], sort_keys=True, default=str),
        **_audit(actor, role, "checks_passed" if passed else "checks_failed: " + ", ".join(failed), {"failed": failed}),
    }))
    if not out:
        raise _illegal(tg, decision, to)
    if not passed and d["authority_level"] == "L2":
        # handled automatically, so undone automatically (BUILD_PROMPT §5 auto-rollback), after recording
        # which valve is suspected of not sealing
        _suspect_valves(tg, decision, x, failed, out[0]["verification"])
        return rollback(tg, decision, AUTO, SYSTEM, "auto_rollback: verification failed")
    return status(tg, decision, do_sweep=False)


def _suspect_valves(tg: TenantGraph, decision: str, x: dict, failed: list[str], verification: str) -> list[str]:
    """After an automatic plan failed its check because water kept flowing, record the valves it closed.
    One closed valve: an active 'stuck' fact (it did not seal), so the next plan will not rely on it. More than
    one: a 'suspect' fact on each, which does not block plans (we cannot tell which one leaks)."""
    if not ({"leak_isolated", "balance_restored"} & set(failed)):
        return []
    closed = [t["valve"] for t in rows(tg.read("execution_tasks", {"execution": x["id"]}))
              if t["phase"] == "forward" and t["status"] == "done" and t["target"] == "closed"]
    kind = "stuck" if len(closed) == 1 else "suspect"
    made = []
    for v in closed:
        rows(tg.write("fact_write", {
            "about": v, "evidence": verification, "id": ids.fact_id(), "kind": kind, "ts": clock.now(),
            "statement": f"{v} was closed by {decision} but the meters showed water still flowing: it may not seal",
            "confidence": config.NOT_SEALING_FACT_CONFIDENCE, "source": "verification"}))
        made.append(v)
    return made


def _after_undo(tg: TenantGraph, decision: str) -> dict | None:
    """When an automatic plan has been undone, plan again, and the new plan always needs a person's OK."""
    st = load(tg, decision)
    x = st["execution"]
    if not x or x.get("rollback_requested_by") != AUTO:
        return None
    record = json.loads(st["decision"]["explain_json"])
    cap = {"reason": "automatic_plan_failed_its_check", "previous": decision,
           "original_fallback": record.get("fallback")}
    new = investigate(tg, st["incident"], AUTO, SYSTEM, auto=False, previous=decision, cap=cap)
    if config.AUTO_TRIAGE:  # the helpers create the jobs for people and the report for the new decision
        tg.write("agent_task_create", {"incident": st["incident"], "id": ids.task_id(), "kind": "dispatch",
                                       "payload": json.dumps({"incident": st["incident"], "decision": new["decision_id"]}),
                                       "ts": clock.now(), "actor": AUTO})
    audit_log.write(tg, decision, kind="decision", actor=AUTO, role=SYSTEM, frm="rolled_back", to="rolled_back",
                reason="escalated_to_people", detail={"new_decision": new["decision_id"], "new_kind": new["kind"],
                                                      "new_authority": new["authority"]["level"]})
    return new


def close_problem(tg: TenantGraph, incident: str, actor: str, role: str, reason: str) -> dict:
    """A person closes a problem fixed outside a verified plan. Refused while a plan is being carried out."""
    _require(role, perm.DECIDERS, "close_problem")
    if not rows(tg.read("incident_get", {"id": incident})):
        raise NotFound("no_such_problem", incident=incident)
    sweep(tg)
    live = rows(tg.read("decisions_for_incident", {"incident": incident, "statuses": list(lifecycle.IN_PROGRESS)}))
    if live:
        raise ExecError("execution_in_progress", decision=live[0]["id"], status=live[0]["status"])
    for o in rows(tg.read("decisions_for_incident", {"incident": incident, "statuses": list(lifecycle.OPEN)})):
        _supersede(tg, o["id"], actor, role, "problem_closed", {"incident": incident})
    p = _audit(actor, role, reason)
    if not rows(tg.write("incident_close", {"id": incident, "by": actor, **p})):
        raise ExecError("not_open", incident=incident)
    return rows(tg.read("incident_get", {"id": incident}))[0]


def on_readings(tg: TenantGraph) -> list[dict]:
    """After new readings arrive, verify every execution that is waiting for them."""
    out = []
    for r in rows(tg.read("decisions_verifying")):
        res = verify(tg, r["decision"], CHECKER, SYSTEM, do_sweep=False)
        out.append({"decision": r["decision"], "status": res["status"], "waiting_for": res.get("waiting_for", [])})
    return out


# ---------------------------------------------------------------- undo / replan


def rollback(tg: TenantGraph, decision: str, actor: str, role: str, reason: str | None = None) -> dict:
    """Undo every move that was applied (or may have been: abandoned steps), newest first, each back to the
    exact valve state and link capacities recorded when the execution started."""
    system = role == SYSTEM
    if not system:
        _require(role, perm.DECIDERS, "rollback")
        sweep(tg)
    st = load(tg, decision)
    d, x = st["decision"], st["execution"]
    if d["status"] not in ("failed", "verified") or x is None:
        raise ExecError("illegal_transition", status=d["status"], to="rolling_back")
    prior = json.loads(x["prior_json"])
    tasks = rows(tg.read("execution_tasks", {"execution": x["id"]}))
    applied = sorted((t for t in tasks if t["phase"] == "forward" and t["status"] in ("done", "abandoned")),
                     key=lambda t: -t["seq"])
    current = dict(rows(tg.read("valves_and_caps"))[0]["valves"])
    moves = []
    for t in applied:
        p = prior[t["valve"]]
        edge_ids = sorted(p["edges"])
        moves.append(Move(t["valve"], p["state"], current[t["valve"]], tuple(edge_ids),
                          tuple(p["edges"][e] for e in edge_ids)))
    cmds = ACTUATOR.commands(x["id"], "rollback", moves)
    p = _audit(actor, role, reason or ("undo" if d["status"] == "verified" else "rollback"),
               {"undo": [f"{m.target}:{m.valve}" for m in moves]})
    out = rows(tg.write("rollback_start", {"decision": decision, "final": "rolling_back" if cmds else "rolled_back",
                                           "tasks": cmds, "audit2": ids.audit_id(), "seq2": clock.next_ns(), **p}))
    if not out:
        raise _illegal(tg, decision, "rolling_back")
    if not cmds:
        _after_undo(tg, decision)
    return status(tg, decision, do_sweep=False)


def replan(tg: TenantGraph, decision: str, actor: str, role: str) -> dict:
    """Investigate the problem again after a plan failed, was undone or was rejected. Valves recorded as stuck
    fail the feasibility check of every new plan that needs them."""
    _require(role, perm.DECIDERS, "replan")
    st = load(tg, decision)
    if st["decision"]["status"] not in lifecycle.REPLANNABLE:
        raise ExecError("illegal_transition", status=st["decision"]["status"], to="replan")
    return investigate(tg, st["incident"], actor, role, previous=decision)
