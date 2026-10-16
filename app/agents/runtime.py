"""Helper runtime: claim a step (Task) from the graph, let the role's chooser pick tools until it finishes, then
write the result and the next steps (HANDED_OFF_TO) back to the graph.

Helpers keep nothing in memory between steps: everything they need is in the Task payload or the graph, so a
helper process can be stopped and started at any time (a claimed step whose lease runs out goes back to open).
Every tool call is recorded as an Episode (kind 'agent_step': role, tool, arguments, result, and the chooser
that actually picked that call: "rules" or the model name, with the reason when the rules stood in for the model).
"""

import json
import os
import time
from dataclasses import dataclass

from app import clock, config, ids
from app.agents import choosers
from app.agents.choosers import Step
from app.agents.roles import ROLES, TASK_KINDS, AgentCtx, Refused
from app.execution import service as execution
from app.graph.client import GraphUnavailable, TenantGraph, rows
from app.memory import episodic


@dataclass
class StepOutcome:
    task: str
    kind: str
    role: str
    incident: str
    status: str
    tools: list[str]
    handed_to: list[str]


def _short(result: dict) -> str:
    return json.dumps(result, default=str, sort_keys=True)[:480]


def run_task(tg: TenantGraph, chooser, claimed: dict) -> StepOutcome:
    role = ROLES[claimed["kind"]]
    payload = json.loads(claimed["payload"] or "{}")
    ctx = AgentCtx(tg, claimed["incident"], claimed["id"], payload, role.name, chooser)
    if role.on_start:
        role.on_start(ctx)
    brief = {"helper": role.title, "step": claimed["kind"], "problem": claimed["incident"],
             **{k: v for k, v in payload.items() if k in ("decision", "segment", "note")}}
    history: list[Step] = []
    for _ in range(config.AGENT_MAX_STEPS):
        call = chooser.choose(role, brief, history)
        if call is None:
            break
        t0 = time.perf_counter()
        tool = role.tools.get(call.name)
        if tool is None:
            result = {"refused": "not_your_tool", "your_tools": sorted(role.tools)}
        else:
            try:
                result = tool.fn(ctx, **call.args)
            except Refused as r:
                result = {"refused": r.code, **r.detail}
            except execution.ExecError as e:
                result = {"refused": e.code, **e.detail}
            except TypeError as e:
                result = {"refused": "bad_arguments", "detail": str(e)}
            except GraphUnavailable:
                raise
        episodic.record(tg, incident=ctx.incident, actor=role.name, kind="agent_step", tool=call.name,
                        args={**call.args, "chooser": call.chooser, "fallback": call.fallback, "task": ctx.task},
                        summary=_short(result),
                        ms=(time.perf_counter() - t0) * 1000, ok="refused" not in result)
        history.append(Step(call, result))
        if ctx.finish:
            break
    if not ctx.finish:  # no finishing tool chosen in time: people take over this step
        ctx.finish = {"status": "failed", "result": {"reason": "no_finish", "steps": len(history)}}
    nxt = [{"id": ids.task_id(), "kind": h["kind"], "payload": json.dumps(h["payload"], default=str, sort_keys=True)}
           for h in ctx.handoffs] if ctx.finish["status"] != "failed" else []
    tg.write("agent_task_finish", {
        "id": ctx.task, "agent": role.name, "status": ctx.finish["status"], "ts": clock.now(),
        "result": json.dumps(ctx.finish["result"], default=str, sort_keys=True),
        "wait_decision": ctx.finish.get("wait_decision"), "wait_seen_status": ctx.finish.get("wait_seen_status"),
        "next": nxt,
    })
    return StepOutcome(ctx.task, claimed["kind"], role.name, ctx.incident, ctx.finish["status"],
                       [s.call.name for s in history], [n["kind"] for n in nxt])


def claim(tg: TenantGraph, chooser, kinds=TASK_KINDS) -> dict | None:
    """Claim the oldest open step, trying the kinds in pipeline order; the Agent node is the role that runs it."""
    for kind in kinds:
        role = ROLES[kind]
        out = rows(tg.write("agent_task_claim", {
            "kinds": [kind], "agent": role.name, "role": role.title, "until": clock.now() + config.AGENT_LEASE_S,
            "ts": clock.now(), "chooser": chooser.name, "pid": os.getpid()}))
        if out:
            return out[0]
    return None


def drain(tg: TenantGraph, chooser=None, max_steps: int = 200) -> list[StepOutcome]:
    """Run helper steps until none is open (time-based changes are applied first each round)."""
    chooser = chooser or choosers.default()
    done: list[StepOutcome] = []
    for _ in range(max_steps):
        execution.sweep(tg)
        c = claim(tg, chooser)
        if c is None:
            break
        done.append(run_task(tg, chooser, c))
    return done


def chain(tg: TenantGraph, incident: str) -> list[dict]:
    """The hand-off chain of one problem, as stored in the graph."""
    out = rows(tg.read("agent_tasks_for_incident", {"incident": incident, "kinds": list(TASK_KINDS)}))
    for r in out:
        r["result"] = json.loads(r.pop("result_json") or "null")
    return out
