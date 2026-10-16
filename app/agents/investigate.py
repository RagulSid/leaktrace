"""Investigate one problem and commit a decision.

The pieces here are shared by two callers, so both make decisions the same way:
  * run(): the fixed sequence behind POST /incidents/{id}/investigate (the P1 path);
  * the role helpers (app/agents/roles.py), where an Investigator and a Planner choose the order of the same
    tools and hand over through Task nodes.
Whatever the order, the gate (enough evidence?), the plan ranking and the authority level are computed
here, in code, from graph results. Weak or contradictory evidence ends in request_evidence (no plans are
evaluated). Every number in a decision comes from a query or algorithm result.
"""

import json
import time

from app import config, ids
from app.agents import tasks
from app.agents.tools import (
    ToolContext, assess_suspect, compute_authority, evaluate_option, find_suspects, generate_options,
    get_incident_context, recall_memory, tool, trace_impact,
)
from app.domain import fingerprint, scoring
from app.domain.authority import AuthorityInput
from app.domain.constraints import PlanResult, is_critical
from app.graph.client import TenantGraph, rows
from app.memory import procedural


@tool(lambda r: f"policy {r['id']}" if r else "no active policy")
def get_policy(ctx: ToolContext, zone: str | None) -> dict | None:
    out = rows(ctx.tg.read("policy_for_zone", {"zone": zone}))
    return out[0]["policy"] if out else None


@tool(lambda r: f"evidence step {r}")
def request_evidence(ctx: ToolContext, zones: list[str], suspect: str | None, missing: list[str], reason: str) -> str:
    return tasks.create(ctx.tg, incident=ctx.incident, kind="inspect", actor=ctx.actor,
                        payload={"zones": zones, "suspect": suspect, "missing": missing, "reason": reason})


@tool(lambda r: f"decision {r}")
def commit_decision(ctx: ToolContext, record: dict, results: list[PlanResult], evidence: list[str],
                    snapshot: dict) -> str:
    """A plan ('act') starts as 'proposed'; anything else is 'recorded'. The graph snapshot the decision was
    computed on is stored with it for the stale-decision guard (app/domain/fingerprint.py)."""
    did = record["decision_id"]
    if results:
        ctx.tg.write("options_write", {"incident": ctx.incident, "source": "system", "options": [
            {"id": r.plan.id, "rank": i, "label": r.plan.label, "ops": r.plan.ops, "valves": r.plan.valves,
             "passed": r.passed, "failed_checks": r.failed_checks, "op_count": r.plan.op_count,
             "checks_json": json.dumps([c.__dict__ for c in r.checks], sort_keys=True),
             "disruption": r.disruption, "steps": r.steps, "rollback": r.plan.rollback}
            for i, r in enumerate(results)
        ]})
    a = record["authority"]
    ctx.tg.write("decision_write", {
        "incident": ctx.incident, "id": did, "kind": record["kind"], "ts": time.time(), "actor": ctx.actor,
        "suspect": record["suspect"]["segment"] if record["suspect"] else None,
        "confidence": record["suspect"]["confidence"]["score"] if record["suspect"] else 0.0,
        "confidence_level": record["suspect"]["confidence"]["level"] if record["suspect"] else "low",
        "signs_agree": record["suspect"]["confidence"]["signs_agree"] if record["suspect"] else 0,
        "signs_total": record["suspect"]["confidence"]["kinds_total"] if record["suspect"] else 0,
        "authority_level": a["level"], "failed_conditions": [f["code"] for f in a["failed"]],
        "summary": record["summary"], "evidence_paths": record["evidence_paths"],
        "explain_json": json.dumps(record, sort_keys=True, default=str),
        "chosen": record["chosen"], "fallback": record["fallback"], "source": "system",
        "status": "proposed" if record["kind"] == "act" else "recorded",
        "requested_by": record["requested_by"], "zone": record["zone"], "policy": record["policy"],
        "fingerprint": fingerprint.fingerprint(snapshot), "snapshot_json": json.dumps(snapshot, sort_keys=True),
    })
    ctx.tg.write("decision_justify", {"id": did, "ids": sorted(set(evidence))})
    if a.get("widened"):  # earned autonomy is always on the audit trail
        from app.execution.audit import write as audit_write

        audit_write(ctx.tg, did, kind="autonomy", actor=ctx.actor, role="system", frm="L3", to="L2",
                    reason="autonomy_widened", detail=a["widened"])
    return did


def _plan_dict(r: PlanResult) -> dict:
    return {"id": r.plan.id, "label": r.plan.label, "ops": r.plan.ops, "passed": r.passed,
            "failed_checks": r.failed_checks, "checks": [c.__dict__ for c in r.checks],
            "disruption": r.disruption, "op_count": r.plan.op_count, "steps": r.steps,
            "rollback": r.plan.rollback, "shortfall": r.shortfall, "starved_critical": r.starved_critical}


# ---------------------------------------------------------------- shared pieces


def min_confidence(policy: dict | None) -> float:
    return policy["min_confidence"] if policy else config.DEFAULT_MIN_CONFIDENCE


def evidence_gate(assessed: list[dict], min_conf: float) -> str | None:
    """None when the strongest suspect is enough to plan for; otherwise why not."""
    ranked = sorted(assessed, key=lambda a: (-a["confidence"]["score"], a["segment"]))
    if not ranked:
        return "no_suspect"
    best = ranked[0]
    ambiguous = (len(ranked) > 1 and ranked[1]["confidence"]["score"] >= min_conf
                 and best["confidence"]["score"] - ranked[1]["confidence"]["score"] < config.AMBIGUITY_MARGIN)
    if ambiguous:
        return "ambiguous"
    if best["confidence"]["contradictions"]:
        return "contradiction"
    if best["confidence"]["score"] < min_conf:
        return "low_confidence"
    return None


def best_of(assessed: list[dict]) -> dict | None:
    ranked = sorted(assessed, key=lambda a: (-a["confidence"]["score"], a["segment"]))
    return ranked[0] if ranked else None


def start_record(incident: str, requested_by: str, assessed: list[dict], policy: dict | None,
                 inc_zones: list[str]) -> tuple[dict, list[str]]:
    """The decision record before any plan, and the evidence ids it rests on."""
    ranked = sorted(assessed, key=lambda a: (-a["confidence"]["score"], a["segment"]))
    best = ranked[0] if ranked else None
    zone = (best["zones"] or [None])[0] if best else (inc_zones or [None])[0]
    record = {
        "decision_id": ids.decision_id(), "incident": incident, "suspect": best,
        "requested_by": requested_by, "zone": zone,
        "other_suspects": [{"segment": a["segment"], "score": a["confidence"]["score"]} for a in ranked[1:]],
        "policy": policy["id"] if policy else None, "min_confidence": min_confidence(policy),
        "plans": [], "chosen": None, "fallback": None, "evidence_paths": [], "impact": None, "memory": None,
    }
    evidence: list[str] = []
    if best:
        evidence += best["signals"]["leak_alarms"] + best["signals"]["pressure_anomalies"]
        evidence += best["signals"]["zone_alarms"] + best["signals"]["report_ids"]
        if best["balance"]["meter"]:
            evidence += [best["balance"]["meter"], *best["balance"]["out_meters"]]
    if policy:
        evidence.append(policy["id"])
    return record, evidence


def commit_evidence_request(ctx: ToolContext, record: dict, evidence: list[str], inc_zones: list[str],
                            reason: str, snapshot: dict, sequence: list[str]) -> dict:
    best = record["suspect"]
    missing = [k for k in ("leak_alarm", "pressure", "flow_imbalance", "reports")
               if best is None or k not in best["confidence"]["kinds"]]
    sequence.append(request_evidence.tool_name)
    task = request_evidence(ctx, zones=inc_zones, suspect=best["segment"] if best else None, missing=missing,
                            reason=reason)
    record.update(kind="request_evidence", evidence_task=task, reason=reason,
                  authority={"level": "L1", "failed": [], "passed": []}, summary=f"request_evidence: {reason}")
    sequence.append(commit_decision.tool_name)
    record["tool_sequence"] = list(sequence)
    commit_decision(ctx, record=record, results=[], evidence=evidence, snapshot=snapshot)
    return record


def plan_inputs(tg: TenantGraph) -> dict:
    consumers = rows(tg.read("consumers_all"))
    return {"sources": rows(tg.read("sources_all"))[0]["ids"], "consumers": consumers,
            "workloads": rows(tg.read("workloads_on", {"ids": [c["id"] for c in consumers]}))}


def critical_min(policy: dict | None) -> int:
    return policy["critical_min_criticality"] if policy else config.DEFAULT_CRITICAL_MIN


def commit_plan(ctx: ToolContext, record: dict, evidence: list[str], policy: dict | None, impact: dict,
                memory: list, gen: dict, results: list[PlanResult], snapshot: dict, sequence: list[str],
                cap: dict | None = None) -> dict:
    """Rank the tested plans, compute the authority level and commit. `cap` ({"reason", "previous"}) means
    the decision may not be handled automatically (used after an automatic plan failed and was undone)."""
    tg = ctx.tg
    best, zone = record["suspect"], record["zone"]
    segment = best["segment"]
    inputs = plan_inputs(tg)
    consumers, workloads = inputs["consumers"], inputs["workloads"]
    ranked = scoring.rank(results)
    chosen, fallback = scoring.choose(ranked)
    sensors = best["signals"]["leak_alarms"] or best["signals"]["zone_alarms"]
    record["evidence_paths"] = [" -> ".join(sensors[:1] + path) for path in impact["paths"].values()]
    record["impact"] = impact
    record["memory"] = memory
    record["boundary"], record["backups"] = gen["boundary"], gen["backups"]
    record["plans"] = [_plan_dict(r) for r in ranked]
    evidence = evidence + [d["consumer"] for d in impact["downstream"]]

    if chosen is None:
        record.update(kind="escalate", authority={"level": "L3", "failed": [{"code": "no_plan_passes"}], "passed": []},
                      summary="escalate: no plan passes every check")
    else:
        cmin = critical_min(policy)
        by_id = {c["id"]: c for c in consumers}
        affected = {d["consumer"] for d in impact["downstream"]} | {k for k, v in chosen.shortfall.items() if v > 0}
        crits = [by_id[c].get("criticality") or 0 for c in affected]
        crits += [w.get("criticality") or 0 for w in workloads if w["consumer"] in affected]
        vp = rows(tg.read("verification_points", {"segment": segment}))[0]
        crit_ids = [c["id"] for c in consumers if is_critical(c, cmin)]
        cm = rows(tg.read("consumer_meters", {"ids": crit_ids}))
        verification = bool(vp["isolation_meters"] or vp["isolation_sensors"]) and all(r["meters"] for r in cm)
        recent = rows(tg.read("actions_recent_in_zone", {"zone": zone, "since": time.time() - config.RATE_WINDOW_S}))[0]["n"]
        playbook = procedural.get(tg, procedural.key(segment, chosen.plan.ops))
        sequence.append(compute_authority.tool_name)
        auth = compute_authority(ctx, inp=AuthorityInput(
            policy=policy, confidence=best["confidence"]["score"],
            contradictions=len(best["confidence"]["contradictions"]),
            starved_critical=len(chosen.starved_critical), max_affected_criticality=max(crits, default=0),
            reversible_feasible=chosen.reversible and "feasible" not in chosen.failed_checks,
            op_count=chosen.plan.op_count, recent_zone_actions=recent, l4_effects=list(chosen.plan.l4_effects),
            rollback_defined=bool(chosen.plan.rollback), verification_defined=verification, playbook=playbook,
        ))
        authority = {"level": auth.level, "failed": auth.failed, "passed": auth.passed}
        if auth.widened:
            authority["widened"] = auth.widened
        if cap and auth.level == "L2":
            authority = {"level": "L3", "failed": [{"code": "auto_attempt_failed", **cap}], "passed": auth.passed}
        record.update(
            kind="act", chosen=chosen.plan.id, fallback=fallback.plan.id if fallback else None, authority=authority,
            verification={"isolation_meters": vp["isolation_meters"], "isolation_sensors": vp["isolation_sensors"],
                          "critical_meters": {r["consumer"]: r["meters"] for r in cm}},
            summary=f"act: {chosen.plan.label} ({authority['level']})",
        )
    if cap:
        record["capped"] = cap
    sequence.append(commit_decision.tool_name)
    record["tool_sequence"] = list(sequence)
    commit_decision(ctx, record=record, results=ranked, evidence=evidence, snapshot=snapshot)
    return record


# ---------------------------------------------------------------- the fixed sequence


def run(tg: TenantGraph, incident: str, actor: str = "planner", requested_by: str = "system",
        cap: dict | None = None) -> dict:
    ctx = ToolContext(tg, incident, actor)
    sequence: list[str] = []
    snapshot = rows(tg.read("world_snapshot"))[0]  # the graph this decision is computed on

    def call(fn, **kw):
        sequence.append(fn.tool_name)
        return fn(ctx, **kw)

    inc = call(get_incident_context)
    suspects = call(find_suspects, zones=inc["zones"])
    assessed = [call(assess_suspect, segment=s["segment"]) for s in suspects[:config.MAX_SUSPECTS_ASSESSED]]
    best = best_of(assessed)
    zone = (best["zones"] or [None])[0] if best else (inc["zones"] or [None])[0]
    policy = call(get_policy, zone=zone)
    record, evidence = start_record(incident, requested_by, assessed, policy, inc["zones"])

    reason = evidence_gate(assessed, min_confidence(policy))
    if reason:  # not enough to act on: ask for evidence instead of guessing
        return commit_evidence_request(ctx, record, evidence, inc["zones"], reason, snapshot, sequence)

    segment = best["segment"]
    impact = call(trace_impact, segment=segment)
    memory = call(recall_memory, segment=segment)
    gen = call(generate_options, segment=segment, key=ids.incident_key(incident))
    inputs = plan_inputs(tg)
    results = [call(evaluate_option, plan=p, segment=segment, sources=inputs["sources"], consumers=inputs["consumers"],
                    exposure=impact["exposure"], workloads=inputs["workloads"], critical_min=critical_min(policy))
               for p in gen["plans"]]
    return commit_plan(ctx, record, evidence, policy, impact, memory, gen, results, snapshot, sequence, cap=cap)


def get_decision(tg: TenantGraph, decision: str) -> dict | None:
    out = rows(tg.read("decision_get", {"id": decision}))
    if not out:
        return None
    d = out[0]
    return {**json.loads(d["decision"]["explain_json"]), "stored": {
        k: v for k, v in d["decision"].items() if k not in ("explain_json", "snapshot_json")}, "chosen_links": d["chosen"],
        "justified_by": sorted(d["evidence"])}
