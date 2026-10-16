"""Break-glass: the only path allowed to act on a plan that needs a person's OK without one (BUILD_PROMPT §5).

Pure rules over the committed decision record (every number in it came from graph queries and max-flow) and
the live policy node.

  trigger  a leak alarm (on the section or in its zone) AND energised equipment near the water
  due      the plan has waited for a person's OK at least policy.break_glass_wait_s
  option   the minimal isolating plan: among plans that cut the leak off, the one with the fewest valve moves
           (lowest disruption on a tie), preferring plans that pass every check
  check    the option must pass envelope conditions 1, 2, 3, 5, 7 and 8:
             policy_active        an active policy, auto mode not paused
             confidence           confidence >= policy.min_confidence and nothing contradicts it
             no_starved_critical  no critical rack loses its required flow
             reversible_feasible  every move can be undone; nothing locked or recorded stuck
             no_life_safety       no life-safety effect
             rollback_and_check   an undo plan and meters to check the result exist
           It may exceed conditions 4 (criticality ceiling) and 6 (move limit), and nothing else.
           It must also be the plan the decision committed to (break-glass never picks a different plan).
"""

from app import config

CONDITIONS = ("policy_active", "confidence", "no_starved_critical", "reversible_feasible", "no_life_safety",
              "rollback_and_check", "is_committed_plan")


def trigger(record: dict) -> dict | None:
    s = record.get("suspect") or {}
    sig = s.get("signals") or {}
    alarms = sorted(set(sig.get("leak_alarms") or []) | set(sig.get("zone_alarms") or []))
    energised = sorted({e["consumer"] for e in ((record.get("impact") or {}).get("exposure") or []) if e.get("energised")})
    if not alarms or not energised:
        return None
    return {"alarms": alarms, "energised_near_water": energised}


def wait_s(policy: dict | None) -> float:
    return float((policy or {}).get("break_glass_wait_s") or config.BREAK_GLASS_WAIT_S)


def due(policy: dict | None, decided_at: float, now: float) -> bool:
    return now - decided_at >= wait_s(policy)


def _check(plan: dict, code: str) -> dict | None:
    return next((c for c in plan.get("checks", []) if c["code"] == code), None)


def minimal_isolation(record: dict) -> dict | None:
    isolating = [p for p in record.get("plans") or [] if (_check(p, "leak_isolated") or {}).get("passed")]
    if not isolating:
        return None
    return min(isolating, key=lambda p: (not p["passed"], p["op_count"], p["disruption"], p["id"]))


def check(record: dict, policy: dict | None) -> dict:
    option = minimal_isolation(record)
    p = policy or {}
    failed: list[str] = []
    if not policy or p.get("status") != "active" or p.get("frozen"):
        failed.append("policy_active")
    conf = (record.get("suspect") or {}).get("confidence") or {}
    min_conf = p.get("min_confidence")
    if min_conf is None or (conf.get("score") or 0) < min_conf or conf.get("contradictions"):
        failed.append("confidence")
    if option is None:
        failed += ["no_starved_critical", "reversible_feasible", "rollback_and_check", "is_committed_plan"]
    else:
        crit_ok = all((_check(option, c) or {}).get("passed") for c in ("critical_supplied", "critical_joint"))
        if option.get("starved_critical") or not crit_ok:
            failed.append("no_starved_critical")
        feas = _check(option, "feasible") or {}
        if not feas.get("passed") or (feas.get("detail") or {}).get("irreversible"):
            failed.append("reversible_feasible")
        v = record.get("verification") or {}
        has_check = bool(v.get("isolation_meters") or v.get("isolation_sensors"))
        if not option.get("rollback") or not has_check:
            failed.append("rollback_and_check")
        if option["id"] != record.get("chosen"):
            failed.append("is_committed_plan")
    if (record.get("authority") or {}).get("level") == "L4":
        failed.append("no_life_safety")
    return {"execute": not failed, "option": option and option["id"], "failed": failed,
            "passed": [c for c in CONDITIONS if c not in failed], "trigger": trigger(record),
            "wait_s": wait_s(policy)}
