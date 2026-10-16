"""The six helpers. Each has plain instructions, its own tools and nothing else, and hands work on only by
creating Task nodes in the graph (runtime.py writes them, with HANDED_OFF_TO links).

  Intake         triage step     look at a new problem, set how urgent it is, pass it to the Investigator
  Investigator   investigate     find the likely cause, see what is affected, recall what we know; then pass to
                                 the Planner, or ask for more evidence
  Planner        plan            list plans, test each with the flow check, commit to one (or escalate)
  Dispatcher     dispatch        start the plan if allowed, create jobs for people, or wait for a person's OK
  Checker        verify          check the result against fresh readings, or wait for them
  Record keeper  record          count the outcome for the playbook, write the incident report

Authority is in code, never in the instructions: every tool checks what may happen, and the execution engine
(app/execution/service.py) applies the same rules as for people. A tool that refuses returns a reason the
helper can read; it never does the thing anyway.
"""

import json
from dataclasses import dataclass, field
from typing import Callable

from app import clock, config, ids
from app.agents import investigate as inv
from app.agents import tools as T
from app.agents.choosers import Step
from app.execution import incident_report, work_orders
from app.execution import service as execution
from app.graph.client import TenantGraph, rows
from app.intake.triage import severity_for_zone
from app.memory import procedural

SYSTEM = execution.SYSTEM


class Refused(Exception):
    def __init__(self, code: str, **detail):
        super().__init__(code)
        self.code, self.detail = code, detail


@dataclass
class AgentCtx:
    tg: TenantGraph
    incident: str
    task: str
    payload: dict
    role: str
    chooser: object = None
    case: dict = field(default_factory=dict)
    handoffs: list[dict] = field(default_factory=list)
    finish: dict | None = None

    @property
    def tool_ctx(self) -> T.ToolContext:
        return T.ToolContext(self.tg, self.incident, self.role)

    def hand_off(self, kind: str, payload: dict) -> None:
        self.handoffs.append({"kind": kind, "payload": {"incident": self.incident, **payload}})

    def done(self, **result) -> dict:
        self.finish = {"status": "done", "result": result}
        return {"ok": True, **result}

    def wait(self, decision: str, seen_status: str, **result) -> dict:
        self.finish = {"status": "waiting", "result": result, "wait_decision": decision, "wait_seen_status": seen_status}
        return {"ok": True, "waiting_for": f"{decision} to leave '{seen_status}'", **result}


@dataclass
class AgentTool:
    name: str
    description: str
    fn: Callable
    params: dict = field(default_factory=dict)  # name -> JSON schema
    required: tuple = ()
    terminal: bool = False

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": {"type": "object", "properties": self.params, "required": list(self.required)}}


@dataclass
class Role:
    name: str
    title: str
    task_kind: str
    prompt: str
    tools: dict
    rules: Callable[[dict, list[Step]], tuple[str, dict] | None]
    on_start: Callable[[AgentCtx], None] | None = None


def _called(history: list[Step], name: str) -> list[Step]:
    return [s for s in history if s.call.name == name]


def _last(history: list[Step], name: str) -> dict | None:
    found = _called(history, name)
    return found[-1].result if found else None


STR = {"type": "string"}
COMMON_RULES = ("You work for LeakTrace, which handles leaks in a cooling-water network. Use only your tools. "
                "Every number comes from a tool; never make one up. Some tools refuse and say why: read the reason "
                "and choose again. People approve risky plans; you cannot get around that. All data is practice "
                "data. Call exactly one tool per turn and end with one of your finishing tools.")


# ---------------------------------------------------------------- shared tools


def look_at_problem(ctx: AgentCtx) -> dict:
    inc = T.get_incident_context(ctx.tool_ctx)
    ctx.case["incident"] = inc
    return {k: inc[k] for k in ("id", "status", "severity", "zones", "involved", "reports", "decisions")}


def _decision(ctx: AgentCtx) -> str:
    did = ctx.payload.get("decision")
    if not did:
        raise Refused("no_decision_in_this_step")
    return did


def decision_status(ctx: AgentCtx) -> dict:
    s = execution.status(ctx.tg, _decision(ctx))
    ctx.case["status"] = s
    return {"decision": s["decision"], "kind": s["kind"], "status": s["status"], "authority_level": s["authority_level"],
            "failed_conditions": s["failed_conditions"], "steps_done": sum(t["status"] == "done" for t in s["tasks"]),
            "steps": len(s["tasks"]), "verification": s["verification"] and s["verification"]["failed_checks"],
            "next_for_people": s["next"]}


LOOK = AgentTool("look_at_problem", "See the problem: its zones, what it involves, reports and earlier decisions.",
                 look_at_problem)
STATUS = AgentTool("decision_status", "See where the decision in this step stands: plan or not, status, "
                   "whether it needs a person's OK, how many valve steps are done, check results.", decision_status)


# ---------------------------------------------------------------- Intake


def suggested_severity(ctx: AgentCtx) -> dict:
    inc = ctx.case.get("incident") or look_at_problem(ctx)
    levels = [severity_for_zone(ctx.tg, z) for z in inc["zones"]] or ["low"]
    order = ["low", "medium", "high"]
    return {"suggested": max(levels, key=order.index), "based_on": "the most critical thing in the problem's zones"}


def set_severity(ctx: AgentCtx, level: str) -> dict:
    if level not in ("low", "medium", "high"):
        raise Refused("bad_level", allowed=["low", "medium", "high"])
    rows(ctx.tg.write("incident_set_severity", {"id": ctx.incident, "severity": level}))
    ctx.case["severity"] = level
    return {"severity": level}


def pass_to_investigator(ctx: AgentCtx, note: str = "") -> dict:
    ctx.hand_off("investigate", {"note": note})
    return ctx.done(passed_to="investigator")


def _intake_rules(brief, h):
    if not _called(h, "look_at_problem"):
        return "look_at_problem", {}
    if not _called(h, "suggested_severity"):
        return "suggested_severity", {}
    if not _called(h, "set_severity"):
        return "set_severity", {"level": _last(h, "suggested_severity")["suggested"]}
    return "pass_to_investigator", {"note": "new problem"}


INTAKE = Role("intake", "Intake", "triage", COMMON_RULES + " You are Intake. Look at the new problem, set how urgent "
              "it is (low, medium or high), then pass it to the Investigator.", {t.name: t for t in [
                  LOOK,
                  AgentTool("suggested_severity", "How urgent the problem looks from the most critical equipment in its "
                            "zones.", suggested_severity),
                  AgentTool("set_severity", "Set how urgent the problem is.", set_severity,
                            {"level": {"type": "string", "enum": ["low", "medium", "high"]}}, ("level",)),
                  AgentTool("pass_to_investigator", "Finish: hand the problem to the Investigator.", pass_to_investigator,
                            {"note": STR}, (), True),
              ]}, _intake_rules)


# ---------------------------------------------------------------- Investigator


def _inv_start(ctx: AgentCtx) -> None:
    ctx.case["snapshot"] = rows(ctx.tg.read("world_snapshot"))[0]  # the graph the decision will rest on
    ctx.case["assessed"] = {}


def find_suspects(ctx: AgentCtx) -> dict:
    inc = ctx.case.get("incident") or (look_at_problem(ctx) and ctx.case["incident"])
    found = T.find_suspects(ctx.tool_ctx, zones=inc["zones"])
    ctx.case["suspects"] = found
    return {"suspects": [{k: s.get(k) for k in ("segment", "zone", "direct_alarms", "downstream_anomalies")}
                         for s in found]}


def _policy(ctx: AgentCtx, zone: str | None) -> dict | None:
    return inv.get_policy(ctx.tool_ctx, zone=zone)


def check_suspect(ctx: AgentCtx, segment: str) -> dict:
    if segment not in {s["segment"] for s in ctx.case.get("suspects") or []}:
        raise Refused("not_a_suspect", hint="call find_suspects and pick one of those sections")
    if segment not in ctx.case["assessed"] and len(ctx.case["assessed"]) >= config.MAX_SUSPECTS_ASSESSED:
        raise Refused("too_many_suspects", limit=config.MAX_SUSPECTS_ASSESSED)
    a = T.assess_suspect(ctx.tool_ctx, segment=segment)
    ctx.case["assessed"][segment] = a
    policy = _policy(ctx, (a["zones"] or [None])[0])
    c = a["confidence"]
    return {"segment": segment, "confidence": c["score"], "level": c["level"], "signs_agree": c["signs_agree"],
            "signs_total": c["kinds_total"], "kinds": c["kinds"], "contradictions": c["contradictions"],
            "balance": a["balance"]["status"], "needed_to_plan": inv.min_confidence(policy),
            "strong_enough": c["score"] >= inv.min_confidence(policy) and not c["contradictions"]}


def trace_impact(ctx: AgentCtx, segment: str) -> dict:
    if segment not in ctx.case["assessed"]:
        raise Refused("check_suspect_first", segment=segment)
    impact = T.trace_impact(ctx.tool_ctx, segment=segment)
    ctx.case["impact"] = impact
    return {"segment": segment, "downstream": [{k: d[k] for k in ("consumer", "criticality", "owners")}
                                               for d in impact["downstream"]],
            "live_equipment_near_water": sorted({e["consumer"] for e in impact["exposure"] if e["energised"]})}


def recall_memory(ctx: AgentCtx, segment: str | None = None) -> dict:
    segment = segment or (ctx.case.get("impact") or {}).get("segment")
    mem = T.recall_memory(ctx.tool_ctx, segment=segment)
    ctx.case["memory"] = mem
    return {"past_problems": sum(len(a["history"]) for a in mem),
            "facts": [{"asset": a["asset"], "facts": a["facts"]} for a in mem if a["facts"]]}


def _record_start(ctx: AgentCtx) -> tuple[dict, list, dict | None, list]:
    assessed = list(ctx.case["assessed"].values())
    best = inv.best_of(assessed)
    inc = ctx.case.get("incident") or (look_at_problem(ctx) and ctx.case["incident"])
    zone = (best["zones"] or [None])[0] if best else (inc["zones"] or [None])[0]
    policy = _policy(ctx, zone)
    record, evidence = inv.start_record(ctx.incident, "helpers", assessed, policy, inc["zones"])
    return record, evidence, policy, assessed


def ask_for_evidence(ctx: AgentCtx, reason: str = "") -> dict:
    record, evidence, policy, assessed = _record_start(ctx)
    why = inv.evidence_gate(assessed, inv.min_confidence(policy)) or "investigator_judgement"
    seq: list[str] = []
    rec = inv.commit_evidence_request(ctx.tool_ctx, record, evidence, ctx.case["incident"]["zones"], why,
                                      ctx.case["snapshot"], seq)
    rec["note"] = reason
    ctx.hand_off("dispatch", {"decision": rec["decision_id"]})
    return ctx.done(decision=rec["decision_id"], kind="request_evidence", reason=why)


def pass_to_planner(ctx: AgentCtx, segment: str, note: str = "") -> dict:
    record, evidence, policy, assessed = _record_start(ctx)
    why = inv.evidence_gate(assessed, inv.min_confidence(policy))
    if why:
        raise Refused("not_enough_evidence", reason=why, hint="ask_for_evidence instead")
    best = inv.best_of(assessed)
    if best["segment"] != segment:
        raise Refused("not_the_strongest_suspect", strongest=best["segment"])
    if (ctx.case.get("impact") or {}).get("segment") != segment:
        raise Refused("trace_impact_first", segment=segment)
    if "memory" not in ctx.case:
        raise Refused("recall_memory_first")
    ctx.hand_off("plan", {"segment": segment, "assessed": assessed, "impact": ctx.case["impact"],
                          "memory": ctx.case["memory"], "zones": ctx.case["incident"]["zones"],
                          "snapshot": ctx.case["snapshot"], "note": note})
    return ctx.done(passed_to="planner", segment=segment)


def _investigator_rules(brief, h):
    if not _called(h, "look_at_problem"):
        return "look_at_problem", {}
    if not _called(h, "find_suspects"):
        return "find_suspects", {}
    suspects = [s["segment"] for s in _last(h, "find_suspects")["suspects"]][:config.MAX_SUSPECTS_ASSESSED]
    checked = {s.call.args["segment"]: s.result for s in _called(h, "check_suspect") if "refused" not in s.result}
    for seg in suspects:
        if seg not in checked:
            return "check_suspect", {"segment": seg}
    strong = sorted((r for r in checked.values() if r["strong_enough"]), key=lambda r: (-r["confidence"], r["segment"]))
    refused = any("refused" in s.result for s in _called(h, "pass_to_planner"))
    if not strong or refused:
        return "ask_for_evidence", {"reason": "the evidence is not strong or clear enough to act on"}
    seg = strong[0]["segment"]
    if not _called(h, "trace_impact"):
        return "trace_impact", {"segment": seg}
    if not _called(h, "recall_memory"):
        return "recall_memory", {"segment": seg}
    return "pass_to_planner", {"segment": seg}


INVESTIGATOR = Role("investigator", "Investigator", "investigate", COMMON_RULES + " You are the Investigator. Find "
                    "the pipe section most likely to be leaking, check how sure we are, see what it affects and "
                    "what we already know about those assets. Pass it to the Planner only when the evidence is "
                    "strong; otherwise ask for more evidence (someone will go and look).", {t.name: t for t in [
                        LOOK,
                        AgentTool("find_suspects", "List pipe sections that could be leaking, from alarms and "
                                  "pressure readings.", find_suspects),
                        AgentTool("check_suspect", "How sure we are that one section is leaking: which signs agree, "
                                  "the meter balance, anything that contradicts it.", check_suspect,
                                  {"segment": STR}, ("segment",)),
                        AgentTool("trace_impact", "What a leak on this section affects: racks downstream, their jobs "
                                  "and owners, live equipment near the water.", trace_impact, {"segment": STR},
                                  ("segment",)),
                        AgentTool("recall_memory", "What we remember about the assets in this problem and the valves "
                                  "a plan for this section could use: earlier problems and known facts (for example "
                                  "a valve that sticks).", recall_memory, {"segment": STR}),
                        AgentTool("ask_for_evidence", "Finish: the evidence is not enough to act on; ask for someone "
                                  "to check on site.", ask_for_evidence, {"reason": STR}, (), True),
                        AgentTool("pass_to_planner", "Finish: hand the most likely section to the Planner. Refused "
                                  "unless the evidence is strong, impact is traced and memory checked.",
                                  pass_to_planner, {"segment": STR, "note": STR}, ("segment",), True),
                    ]}, _investigator_rules, _inv_start)


# ---------------------------------------------------------------- Planner


def _plan_start(ctx: AgentCtx) -> None:
    ctx.case["results"] = {}


def read_findings(ctx: AgentCtx) -> dict:
    p = ctx.payload
    best = inv.best_of(p["assessed"])
    return {"segment": p["segment"], "confidence": best["confidence"]["score"],
            "affected": [d["consumer"] for d in p["impact"]["downstream"]],
            "known_facts": [f for a in p["memory"] for f in a["facts"]]}


def list_plans(ctx: AgentCtx) -> dict:
    gen = T.generate_options(ctx.tool_ctx, segment=ctx.payload["segment"], key=ids.incident_key(ctx.incident))
    ctx.case["gen"] = gen
    return {"plans": [{"id": p.id, "plan": p.label} for p in gen["plans"]]}


def test_plan(ctx: AgentCtx, plan_id: str) -> dict:
    gen = ctx.case.get("gen")
    plan = next((p for p in (gen or {}).get("plans", []) if p.id == plan_id), None)
    if plan is None:
        raise Refused("unknown_plan", hint="call list_plans and use one of those ids")
    if "inputs" not in ctx.case:
        ctx.case["inputs"] = inv.plan_inputs(ctx.tg)
        ctx.case["policy"] = _policy(ctx, (inv.best_of(ctx.payload["assessed"])["zones"] or [None])[0])
    i = ctx.case["inputs"]
    r = T.evaluate_option(ctx.tool_ctx, plan=plan, segment=ctx.payload["segment"], sources=i["sources"],
                          consumers=i["consumers"], exposure=ctx.payload["impact"]["exposure"], workloads=i["workloads"],
                          critical_min=inv.critical_min(ctx.case["policy"]))
    ctx.case["results"][plan_id] = r
    return {"plan": plan.label, "passes_every_check": r.passed, "failed_checks": r.failed_checks,
            "disruption": r.disruption, "racks_short": {k: v for k, v in r.shortfall.items() if v > 0}}


def commit_decision(ctx: AgentCtx, note: str = "") -> dict:
    gen = ctx.case.get("gen")
    if not gen:
        raise Refused("list_plans_first")
    untested = [p.id for p in gen["plans"] if p.id not in ctx.case["results"]]
    if untested:
        raise Refused("untested_plans", plans=untested)
    live = rows(ctx.tg.read("decisions_for_incident", {"incident": ctx.incident, "statuses": ["executing", "verifying",
                                                                                               "rolling_back"]}))
    if live:
        raise Refused("execution_in_progress", decision=live[0]["id"])
    p = ctx.payload
    record, evidence = inv.start_record(ctx.incident, "helpers", p["assessed"], ctx.case["policy"], p["zones"])
    rec = inv.commit_plan(ctx.tool_ctx, record, evidence, ctx.case["policy"], p["impact"], p["memory"], gen,
                          [ctx.case["results"][pl.id] for pl in gen["plans"]], p["snapshot"], [])
    for o in rows(ctx.tg.read("decisions_for_incident", {"incident": ctx.incident, "statuses": ["proposed", "approved"]})):
        if o["id"] != rec["decision_id"]:
            execution._supersede(ctx.tg, o["id"], "planner", SYSTEM, "newer_decision", {"by": rec["decision_id"]})
    ctx.hand_off("dispatch", {"decision": rec["decision_id"]})
    return ctx.done(decision=rec["decision_id"], kind=rec["kind"], summary=rec["summary"],
                    authority=rec["authority"]["level"])


def _planner_rules(brief, h):
    if not _called(h, "read_findings"):
        return "read_findings", {}
    if not _called(h, "list_plans"):
        return "list_plans", {}
    tested = {s.call.args["plan_id"] for s in _called(h, "test_plan")}
    for p in _last(h, "list_plans")["plans"]:
        if p["id"] not in tested:
            return "test_plan", {"plan_id": p["id"]}
    return "commit_decision", {}


PLANNER = Role("planner", "Planner", "plan", COMMON_RULES + " You are the Planner. List the possible valve plans, "
               "test every one with the flow check, then commit. The engine picks the best plan that passes every "
               "check and decides whether a person must approve it; if none passes, people decide.",
               {t.name: t for t in [
                   AgentTool("read_findings", "What the Investigator found: the section, how sure we are, what is "
                             "affected, known facts.", read_findings),
                   AgentTool("list_plans", "List the valve plans that could cut this section off.", list_plans),
                   AgentTool("test_plan", "Test one plan with the flow check: does the leak stop, do critical racks "
                             "keep their water, can every valve move.", test_plan, {"plan_id": STR}, ("plan_id",)),
                   AgentTool("commit_decision", "Finish: commit the decision once every plan is tested.",
                             commit_decision, {"note": STR}, (), True),
               ]}, _planner_rules, _plan_start)


# ---------------------------------------------------------------- Dispatcher


def start_plan(ctx: AgentCtx) -> dict:
    did = _decision(ctx)
    try:
        s = execution.execute(ctx.tg, did, "dispatcher", SYSTEM)
    except execution.ExecError as e:
        if e.code == "stale_decision":  # the graph changed: the new decision gets its own dispatch step
            ctx.hand_off("dispatch", {"decision": e.detail["new_decision"]})
        raise Refused(e.code, **e.detail)
    return {"status": s["status"], "steps": [f"{t['target']} {t['valve']}" for t in s["tasks"]]}


def create_work_orders(ctx: AgentCtx) -> dict:
    made = work_orders.create_for_decision(ctx.tg, _decision(ctx), "dispatcher")
    ctx.case["work_orders"] = True
    return {"created": made}


def wait_for_approval(ctx: AgentCtx) -> dict:
    s = execution.status(ctx.tg, _decision(ctx))
    if s["status"] != "proposed":
        raise Refused("not_waiting_for_approval", status=s["status"])
    return ctx.wait(s["decision"], s["status"])


def pass_to_checker(ctx: AgentCtx) -> dict:
    s = execution.status(ctx.tg, _decision(ctx))
    if s["status"] not in ("executing", "verifying", "verified", "failed", "rolling_back", "rolled_back",
                           "rollback_failed"):
        raise Refused("plan_not_started", status=s["status"])
    ctx.hand_off("verify", {"decision": s["decision"]})
    return ctx.done(passed_to="checker")


def pass_to_record_keeper(ctx: AgentCtx, note: str = "") -> dict:
    s = execution.status(ctx.tg, _decision(ctx))
    if s["kind"] == "act" and s["status"] in ("proposed", "approved", "executing", "verifying", "rolling_back"):
        raise Refused("still_in_progress", status=s["status"])
    ctx.hand_off("record", {"decision": s["decision"], "note": note})
    return ctx.done(passed_to="record_keeper")


def _dispatcher_rules(brief, h):
    if not _called(h, "decision_status"):
        return "decision_status", {}
    st = _called(h, "decision_status")[-1].result
    if st["kind"] != "act" or st["status"] in ("rejected", "superseded"):
        if st["kind"] != "act" and not _called(h, "create_work_orders"):
            return "create_work_orders", {}
        return "pass_to_record_keeper", {"note": st["kind"]}
    started = _called(h, "start_plan")
    if st["status"] in ("proposed", "approved") and not started:
        return "start_plan", {}
    if started and "refused" in started[-1].result:
        code = started[-1].result["refused"]
        if code in ("needs_approval", "approval_expired"):
            if not _called(h, "create_work_orders"):
                return "create_work_orders", {}
            return "wait_for_approval", {}
        return "pass_to_record_keeper", {"note": code}
    if not _called(h, "create_work_orders"):
        return "create_work_orders", {}
    return "pass_to_checker", {}


DISPATCHER = Role("dispatcher", "Dispatcher", "dispatch", COMMON_RULES + " You are the Dispatcher. Start the "
                  "committed plan if it is allowed (the engine refuses if a person must approve first), create the "
                  "jobs people must do, then pass the plan to the Checker. If it needs a person's OK, wait for it. "
                  "If there is nothing to start, pass it to the Record keeper.", {t.name: t for t in [
                      STATUS,
                      AgentTool("start_plan", "Start the valve moves of the committed plan. Refused unless auto mode "
                                "allows it or a person has approved it.", start_plan),
                      AgentTool("create_work_orders", "Create the jobs for people: inspect the area, move or warn "
                                "about jobs on racks that lose water, or agree a plan when none passes.",
                                create_work_orders),
                      AgentTool("wait_for_approval", "Finish for now: wait until a person approves or rejects the plan.",
                                wait_for_approval, terminal=True),
                      AgentTool("pass_to_checker", "Finish: the plan has started; hand it to the Checker.",
                                pass_to_checker, terminal=True),
                      AgentTool("pass_to_record_keeper", "Finish: nothing to start (evidence request, people decide, "
                                "rejected or replaced); hand it to the Record keeper.", pass_to_record_keeper,
                                {"note": STR}, (), True),
                  ]}, _dispatcher_rules)


# ---------------------------------------------------------------- Checker


def check_result(ctx: AgentCtx) -> dict:
    did = _decision(ctx)
    s = execution.status(ctx.tg, did)
    if s["status"] != "verifying":
        return {"status": s["status"], "checked": False}
    r = execution.verify(ctx.tg, did, "checker", SYSTEM)
    return {"status": r["status"], "checked": not r.get("waiting_for"), "waiting_for": r.get("waiting_for", []),
            "failed_checks": r["verification"] and r["verification"]["failed_checks"]}


def wait(ctx: AgentCtx) -> dict:
    s = execution.status(ctx.tg, _decision(ctx))
    if s["status"] not in ("approved", "executing", "verifying", "rolling_back"):
        raise Refused("nothing_to_wait_for", status=s["status"])
    return ctx.wait(s["decision"], s["status"])


FINAL = ("verified", "failed", "rolled_back", "rollback_failed", "rejected", "superseded")


def _checker_rules(brief, h):
    if not _called(h, "decision_status"):
        return "decision_status", {}
    st = _called(h, "decision_status")[-1].result["status"]
    if st == "verifying" and not _called(h, "check_result"):
        return "check_result", {}
    if _called(h, "check_result"):
        st = _last(h, "check_result")["status"]
    return ("pass_to_record_keeper", {}) if st in FINAL else ("wait", {})


CHECKER = Role("checker", "Checker", "verify", COMMON_RULES + " You are the Checker. When the valve moves are done, "
               "check the result against fresh meter readings. If readings are not in yet or moves are still "
               "running, wait. When the result is final (worked, failed or undone), pass it to the Record keeper. "
               "A failed automatic plan is undone by the engine on its own.", {t.name: t for t in [
                   STATUS,
                   AgentTool("check_result", "Compare fresh readings with what the plan expected.", check_result),
                   AgentTool("wait", "Finish for now: wait for the moves or the readings.", wait, terminal=True),
                   AgentTool("pass_to_record_keeper", "Finish: the result is final; hand it to the Record keeper.",
                             pass_to_record_keeper, {"note": STR}, (), True),
               ]}, _checker_rules)


# ---------------------------------------------------------------- Record keeper


def update_playbook(ctx: AgentCtx) -> dict:
    s = execution.status(ctx.tg, _decision(ctx))
    if s["kind"] != "act" or not s["execution"]:
        return {"updated": False, "why": "no plan was carried out"}
    record = json.loads(execution.load(ctx.tg, s["decision"])["decision"]["explain_json"])
    if s["status"] == "verified":
        verified = True
    elif s["status"] in ("failed", "rolled_back", "rollback_failed"):
        verified = False
    else:
        return {"updated": False, "why": f"status {s['status']}"}
    pb = procedural.record_outcome(ctx.tg, s["decision"], record["suspect"]["segment"], s["plan"]["ops"], verified)
    return {"updated": pb["counted"], "playbook": pb["id"], "successes": pb["success_count"],
            "failures": pb["failure_count"]}


def write_incident_report(ctx: AgentCtx) -> dict:
    writer = getattr(ctx.chooser, "prose_writer", None)
    r = incident_report.write(ctx.tg, ctx.incident, "record_keeper", writer=writer)
    ctx.case["report"] = r["id"]
    return {"report": r["id"], "prose_by": r["prose_by"], "prose": r["prose"][:600]}


def finish(ctx: AgentCtx) -> dict:
    if "report" not in ctx.case:
        raise Refused("write_incident_report_first")
    return ctx.done(report=ctx.case["report"])


def _record_keeper_rules(brief, h):
    for name in ("decision_status", "update_playbook", "write_incident_report"):
        if not _called(h, name):
            return name, {}
    return "finish", {}


RECORD_KEEPER = Role("record_keeper", "Record keeper", "record", COMMON_RULES + " You are the Record keeper. Count "
                     "how the plan turned out for its playbook (the engine decides success or failure from the graph), "
                     "write the incident report, then finish.", {t.name: t for t in [
                         STATUS,
                         AgentTool("update_playbook", "Count this outcome for the plan's playbook (what worked "
                                   "before on this section).", update_playbook),
                         AgentTool("write_incident_report", "Write the incident report from the facts in the graph.",
                                   write_incident_report),
                         AgentTool("finish", "Finish this step.", finish, terminal=True),
                     ]}, _record_keeper_rules)


ROLES = {r.task_kind: r for r in (INTAKE, INVESTIGATOR, PLANNER, DISPATCHER, CHECKER, RECORD_KEEPER)}
TASK_KINDS = tuple(ROLES)
assert set(TASK_KINDS) == set(execution.AGENT_TASK_KINDS)


def now() -> float:
    return clock.now()
