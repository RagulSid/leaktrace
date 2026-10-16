"""Hard constraints for one plan, as pure functions over numbers the graph produced.

The flow numbers come from algo.maxFlow under the plan's what-if capacities (see app/agents/tools.py);
nothing here invents or estimates a flow.

Checks (BUILD_PROMPT §10):
  leak_isolated       max flow from every source to the leaking section is 0
  critical_supplied   each critical consumer, checked alone, still receives its required flow
  critical_joint      all critical consumers together still receive their required flow
  energised_exposure  energised equipment near the water is only acceptable if the leak is cut off
                      (the plan then carries an inspection step for the zone)
  workloads_handled   every workload on a rack that loses flow gets a step (migrate or inform owners);
                      a critical workload that cannot be migrated fails
  feasible            no valve the plan moves is locked or recorded as stuck

Shortfall: each consumer's own shortfall (required minus its max flow alone, with links into consumers
capped at their demand), plus the joint deficit when they share pipes (sum of individual flows minus the
max flow to all of them together). The joint deficit is assigned to the least critical consumers first,
which is what operators throttle first. Disruption = sum of criticality x shortfall / required.
"""

from dataclasses import dataclass, field

from app.domain.options import Plan

EPS = 1e-6


@dataclass
class PlanNumbers:
    leak_inflow: float
    consumer_flow: dict[str, float]  # each consumer alone, demand-capped
    all_flow: float  # all consumers together, demand-capped
    critical_joint_flow: float  # critical consumers together, demand-capped
    valve_flags: dict[str, dict]  # id -> {state, locked, reversible, stuck: [{fact, statement}]}
    exposure: list[dict]  # [{zone, consumer, energised}]
    workloads: list[dict]  # rows of workloads_on


@dataclass
class Check:
    code: str
    passed: bool
    detail: dict = field(default_factory=dict)


@dataclass
class PlanResult:
    plan: Plan
    checks: list[Check]
    shortfall: dict[str, float]
    disruption: float
    steps: list[str]
    starved_critical: list[str]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> list[str]:
        return [c.code for c in self.checks if not c.passed]

    @property
    def reversible(self) -> bool:
        flags = next(c for c in self.checks if c.code == "feasible").detail.get("irreversible", [])
        return not flags


def is_critical(consumer: dict, critical_min: int) -> bool:
    return (consumer.get("criticality") or 0) >= critical_min


def evaluate(plan: Plan, n: PlanNumbers, consumers: list[dict], critical_min: int) -> PlanResult:
    by_id = {c["id"]: c for c in consumers}
    critical = [c for c in consumers if is_critical(c, critical_min)]
    checks: list[Check] = []
    steps: list[str] = []

    isolated = n.leak_inflow <= EPS
    checks.append(Check("leak_isolated", isolated, {"flow_into_leak": n.leak_inflow}))

    # shortfall per consumer: alone, then the shared-pipe deficit to the least critical first
    short = {cid: max(0.0, by_id[cid]["required_flow"] - f) for cid, f in n.consumer_flow.items()}
    deficit = max(0.0, sum(n.consumer_flow.values()) - n.all_flow)
    for c in sorted(consumers, key=lambda c: (c.get("criticality") or 0, c["id"])):
        if deficit <= EPS:
            break
        room = n.consumer_flow[c["id"]]
        take = min(room, deficit)
        short[c["id"]] += take
        deficit -= take
    short = {k: round(v, 3) for k, v in short.items()}

    alone = {c["id"]: {"flow": n.consumer_flow[c["id"]], "required": c["required_flow"]} for c in critical}
    checks.append(Check(
        "critical_supplied",
        all(v["flow"] + EPS >= v["required"] for v in alone.values()),
        {"consumers": alone},
    ))
    need = sum(c["required_flow"] for c in critical)
    checks.append(Check(
        "critical_joint",
        n.critical_joint_flow + EPS >= need,
        {"flow": n.critical_joint_flow, "required": need},
    ))

    energised = [e for e in n.exposure if e.get("energised")]
    if energised:
        for z in sorted({e["zone"] for e in energised}):
            steps.append(f"inspect:{z}")
    checks.append(Check(
        "energised_exposure",
        isolated or not energised,
        {"energised_near_water": sorted({e["consumer"] for e in energised})},
    ))

    blocked = []
    for w in n.workloads:
        if short.get(w["consumer"], 0) <= EPS:
            continue
        if w.get("migratable"):
            steps.append(f"migrate:{w['workload']}")
        elif (w.get("criticality") or 0) >= critical_min:
            blocked.append(w["workload"])
        else:
            steps.append(f"inform:{w['workload']}")
    checks.append(Check("workloads_handled", not blocked, {"cannot_move": blocked}))

    locked, stuck, irreversible, unknown = [], [], [], []
    for v in plan.valves:
        f = n.valve_flags.get(v)
        if f is None:
            unknown.append(v)
            continue
        if f.get("locked"):
            locked.append(v)
        if f.get("stuck"):
            stuck.append({"valve": v, "facts": [s["fact"] for s in f["stuck"]]})
        if f.get("reversible") is False:
            irreversible.append(v)
    checks.append(Check(
        "feasible",
        not (locked or stuck or unknown),
        {"locked": locked, "stuck": stuck, "unknown": unknown, "irreversible": irreversible},
    ))

    disruption = round(sum(
        (by_id[cid].get("criticality") or 0) * s / by_id[cid]["required_flow"]
        for cid, s in short.items() if s > EPS
    ), 3)
    starved = sorted(c["id"] for c in critical if short[c["id"]] > EPS)
    return PlanResult(plan, checks, short, disruption, steps, starved)
