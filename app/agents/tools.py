"""Domain tools the helpers use. Each one is a thin layer over saved graph queries and algorithms, and
every call is recorded as an Episode (tool, arguments, short result summary, duration).

The same functions back the MCP server (app/mcp_server/server.py) and the investigation sequence
(app/agents/investigate.py). None of them takes a tenant: the graph handle is bound by the caller.
"""

import functools
import time
from dataclasses import asdict, dataclass

from app.domain import confidence as conf
from app.domain import constraints, options
from app.domain.authority import AuthorityInput, AuthorityResult, compute
from app.graph import whatif
from app.graph.algo import max_flow
from app.graph.client import GraphUnavailable, TenantGraph, rows
from app.memory import episodic


@dataclass
class ToolContext:
    tg: TenantGraph
    incident: str | None
    actor: str


def tool(summarize):
    """Record each call as an Episode. If FalkorDB is down nothing can be recorded and the error propagates."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(ctx: ToolContext, **kwargs):
            t0 = time.perf_counter()
            try:
                out = fn(ctx, **kwargs)
            except GraphUnavailable:
                raise
            except Exception as e:
                episodic.record(ctx.tg, incident=ctx.incident, actor=ctx.actor, kind="tool_call", tool=fn.__name__,
                                args=_args(kwargs), summary=f"error: {e}", ms=(time.perf_counter() - t0) * 1000, ok=False)
                raise
            episodic.record(ctx.tg, incident=ctx.incident, actor=ctx.actor, kind="tool_call", tool=fn.__name__,
                            args=_args(kwargs), summary=summarize(out), ms=(time.perf_counter() - t0) * 1000, ok=True)
            return out

        wrapper.tool_name = fn.__name__
        return wrapper

    return deco


def _args(kwargs: dict) -> dict:
    out = {}
    for k, v in kwargs.items():
        if isinstance(v, options.Plan):
            out[k] = v.id
        elif isinstance(v, (list, dict)) and len(repr(v)) > 300:
            out[k] = f"<{type(v).__name__} of {len(v)}>"
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------- reads


@tool(lambda r: f"problem {r['id']}, zones {r['zones']}, {len(r['reports'])} reports")
def get_incident_context(ctx: ToolContext) -> dict:
    out = rows(ctx.tg.read("incident_get", {"id": ctx.incident}))
    if not out:
        raise LookupError(f"no incident {ctx.incident}")
    return out[0]


@tool(lambda r: f"{len(r)} suspects" + (f"; top {r[0]['segment']}" if r else ""))
def find_suspects(ctx: ToolContext, zones: list[str]) -> list[dict]:
    """Q1, limited to the problem's zones. With no leak alarm at all, every section in those zones is a
    (weak) suspect, so the evidence step can still run and ask for more evidence."""
    found = [r for r in rows(ctx.tg.read("q1_find_suspects")) if not zones or r["zone"] in zones]
    if found:
        return found
    return [{"segment": r["segment"], "zone": r["zone"], "direct_alarms": 0, "downstream_anomalies": 0,
             "zone_alarms": 0} for r in rows(ctx.tg.read("segments_in_zones", {"zones": zones}))]


@tool(lambda r: f"{r['segment']}: confidence {r['confidence']['score']} ({r['confidence']['signs_agree']} of "
                f"{r['confidence']['kinds_total']} signs), balance {r['balance']['status']}")
def assess_suspect(ctx: ToolContext, segment: str) -> dict:
    sig = rows(ctx.tg.read("segment_signals", {"segment": segment}))[0]
    rep = rows(ctx.tg.read("reports_near_segment", {"segment": segment, "incident": ctx.incident}))
    rep = rep[0] if rep else {"reports": 0, "reporters": 0, "report_ids": []}
    balance = conf.balance_view(rows(ctx.tg.read("flow_balance_for_segment", {"segment": segment})))
    c = conf.assess(conf.Signals(
        leak_alarms=sig["leak_alarms"], zone_alarms=sig["zone_alarms"],
        pressure_anomalies=sig["pressure_anomalies"], reports=rep["reports"], reporters=rep["reporters"],
        balance=balance,
    ))
    return {
        "segment": segment, "zones": sig["zones"],
        "signals": {"leak_alarms": sig["leak_alarms"], "zone_alarms": sig["zone_alarms"],
                    "pressure_anomalies": sig["pressure_anomalies"], "report_ids": rep["report_ids"],
                    "reporters": rep["reporters"]},
        "balance": asdict(balance),
        "confidence": {"score": c.score, "level": c.level, "signs_agree": c.signs_agree, "kinds_total": c.kinds_total,
                       "kinds": c.kinds_present, "contradictions": c.contradictions, "parts": c.parts},
    }


@tool(lambda r: f"{len(r['downstream'])} downstream, {len(r['exposure'])} near the water")
def trace_impact(ctx: ToolContext, segment: str) -> dict:
    """Q2 (downstream consumers, workloads, owners) and Q3 (exposure, power feeds), plus the map path
    from the section to each downstream consumer."""
    down = rows(ctx.tg.read("q2_trace_impact", {"segment": segment}))
    paths = {}
    for d in down:
        p = rows(ctx.tg.read("evidence_path", {"segment": segment, "consumer": d["consumer"]}))
        if p:
            paths[d["consumer"]] = p[0]["ids"]
    return {"segment": segment, "downstream": down, "paths": paths,
            "exposure": rows(ctx.tg.read("q3_exposure", {"segment": segment}))}


@tool(lambda r: f"{sum(len(a['history']) for a in r)} past problems, {sum(len(a['facts']) for a in r)} facts")
def recall_memory(ctx: ToolContext, segment: str | None = None) -> list[dict]:
    """Q4: earlier problems on the same assets with their decisions, and active facts about them. With a
    section, also the facts about the valves a plan for it could use (its boundary valves and the closed
    backup valves), so a valve recorded stuck is known before planning."""
    out = rows(ctx.tg.read("q4_recall_incidents", {"incident": ctx.incident}))
    if segment:
        seen = {a["asset"] for a in out}
        valves = [r["id"] for r in rows(ctx.tg.read("boundary_valves", {"segment": segment}))]
        valves += [r["id"] for r in rows(ctx.tg.read("closed_valves"))]
        facts: dict[str, list[str]] = {}
        for f in rows(ctx.tg.read("facts_about", {"ids": sorted(set(valves) - seen)})):
            facts.setdefault(f["about"], []).append(f["statement"])
        out += [{"asset": v, "history": [], "facts": fs} for v, fs in sorted(facts.items())]
    return out


@tool(lambda r: f"{len(r['plans'])} plans from boundary {r['boundary']} and backups {r['backups']}")
def generate_options(ctx: ToolContext, segment: str, key: str) -> dict:
    boundary = [r["id"] for r in rows(ctx.tg.read("boundary_valves", {"segment": segment}))]
    backups = [r["id"] for r in rows(ctx.tg.read("closed_valves"))]
    return {"boundary": boundary, "backups": backups, "plans": options.generate(key, boundary, backups)}


@tool(lambda r: f"{r.plan.id} ({r.plan.label}): " + ("pass" if r.passed else "fail " + ",".join(r.failed_checks)))
def evaluate_option(ctx: ToolContext, plan: options.Plan, segment: str, sources: list[str], consumers: list[dict],
                    exposure: list[dict], workloads: list[dict], critical_min: int) -> constraints.PlanResult:
    """What-if for one plan: write its capacities, run algo.maxFlow into the leak and into every
    consumer (alone, all together, critical ones together), then apply the hard checks."""
    flags = {r["id"]: {**r, "stuck": [s for s in r["stuck"] if s.get("fact")]}
             for r in rows(ctx.tg.read("asset_flags", {"ids": plan.valves}))} if plan.valves else {}
    critical = [c["id"] for c in consumers if constraints.is_critical(c, critical_min)]
    with whatif.variant(ctx.tg, plan.id, plan.close, plan.open, demand_caps=True) as cap:
        leak = max_flow(ctx.tg, sources, [segment], cap).max_flow
        alone = {c["id"]: max_flow(ctx.tg, sources, [c["id"]], cap).max_flow for c in consumers}
        together = max_flow(ctx.tg, sources, [c["id"] for c in consumers], cap).max_flow
        crit_joint = max_flow(ctx.tg, sources, critical, cap).max_flow if critical else 0.0
    numbers = constraints.PlanNumbers(leak, alone, together, crit_joint, flags, exposure, workloads)
    return constraints.evaluate(plan, numbers, consumers, critical_min)


@tool(lambda r: f"{r.level}" + (f", failed {r.failed_codes}" if r.failed else ""))
def compute_authority(ctx: ToolContext, inp: AuthorityInput) -> AuthorityResult:
    return compute(inp)
