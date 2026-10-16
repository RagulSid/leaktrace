"""How much the agent may do on its own for one committed plan (BUILD_PROMPT §5).

Deterministic: every input comes from graph results (policy node, confidence formula, max-flow checks,
registry flags, memory facts, recent actions). The model never sets or overrides any of it.

L2 (handled automatically) only if all eight envelope conditions hold:
  policy_active        an active policy applies to the zone and auto mode is not paused
  confidence           confidence >= policy.min_confidence and no contradicting evidence
  no_starved_critical  no critical consumer loses its required flow (max flow, one at a time and jointly)
  criticality_ceiling  every affected consumer and workload is at or below policy.max_auto_criticality
  reversible_feasible  every valve move can be undone and none is locked or stuck
  operation_limit      moves <= policy.max_auto_operations and the zone's hourly action limit is not hit
  no_life_safety       no L4-class effect
  rollback_and_check   an undo plan and a verification check exist before acting
Any failure gives L3 (needs approval) with the failing conditions listed; an L4-class effect gives L4.

Earned autonomy: if the only thing above the ceiling is criticality, and a playbook for the same plan on the
same section has at least policy.min_playbook_successes verified successes and no failures, the ceiling is
widened for this decision, but never above policy.auto_promotion_ceiling (set by the Manager). The widening
is returned in `widened` and written to the audit trail. Nothing else is ever widened, and nothing here can
change the policy itself.
"""

from dataclasses import dataclass, field

from app import config

CONDITIONS = (
    "policy_active",
    "confidence",
    "no_starved_critical",
    "criticality_ceiling",
    "reversible_feasible",
    "operation_limit",
    "no_life_safety",
    "rollback_and_check",
)


@dataclass
class AuthorityInput:
    policy: dict | None
    confidence: float
    contradictions: int
    starved_critical: int
    max_affected_criticality: int
    reversible_feasible: bool
    op_count: int
    recent_zone_actions: int
    l4_effects: list[str] = field(default_factory=list)
    rollback_defined: bool = True
    verification_defined: bool = True
    playbook: dict | None = None  # {id, success_count, failure_count} for this plan on this section


@dataclass
class AuthorityResult:
    level: str  # "L2" | "L3" | "L4"
    failed: list[dict]
    passed: list[str]
    widened: dict | None = None

    @property
    def failed_codes(self) -> list[str]:
        return [f["code"] for f in self.failed]


def compute(i: AuthorityInput) -> AuthorityResult:
    p = i.policy or {}
    has_policy = bool(i.policy) and p.get("status") == "active"
    failed: list[dict] = []

    def fail(code: str, **detail):
        failed.append({"code": code, **detail})

    if not has_policy:
        fail("policy_active", reason="no_active_policy")
    elif p.get("frozen"):
        fail("policy_active", reason="auto_mode_paused")

    min_conf = p.get("min_confidence")
    if min_conf is None or i.confidence < min_conf:
        fail("confidence", value=i.confidence, required=min_conf)
    elif i.contradictions:
        fail("confidence", value=i.confidence, required=min_conf, contradictions=i.contradictions)

    if i.starved_critical:
        fail("no_starved_critical", count=i.starved_critical)

    ceiling = p.get("max_auto_criticality")
    widened = None
    if ceiling is None or i.max_affected_criticality > ceiling:
        earned = earned_ceiling(p, i.playbook)
        if ceiling is not None and earned is not None and i.max_affected_criticality <= earned:
            widened = {"from": ceiling, "to": earned, "playbook": i.playbook["id"],
                       "successes": i.playbook["success_count"], "value": i.max_affected_criticality}
        else:
            fail("criticality_ceiling", value=i.max_affected_criticality, allowed=ceiling,
                 **({"earned_up_to": earned} if earned is not None else {}))

    if not i.reversible_feasible:
        fail("reversible_feasible")

    max_ops, rate = p.get("max_auto_operations"), p.get("rate_limit_per_zone_per_hour")
    if max_ops is None or i.op_count > max_ops:
        fail("operation_limit", value=i.op_count, allowed=max_ops)
    elif rate is None or i.recent_zone_actions >= rate:
        fail("operation_limit", recent_zone_actions=i.recent_zone_actions, allowed_per_hour=rate)

    if i.l4_effects:
        fail("no_life_safety", effects=list(i.l4_effects))

    if not (i.rollback_defined and i.verification_defined):
        fail("rollback_and_check", rollback=i.rollback_defined, verification=i.verification_defined)

    codes = {f["code"] for f in failed}
    level = "L4" if i.l4_effects else ("L3" if failed else "L2")
    return AuthorityResult(level, failed, [c for c in CONDITIONS if c not in codes],
                           widened if not failed and level == "L2" else None)


def earned_ceiling(policy: dict, playbook: dict | None) -> int | None:
    """The widened criticality ceiling a proven playbook earns, or None. Bounded by the Manager's ceiling."""
    if not playbook:
        return None
    need = policy.get("min_playbook_successes") or config.MIN_PLAYBOOK_SUCCESSES
    top = policy.get("auto_promotion_ceiling")
    if top is None or (playbook.get("success_count") or 0) < need or (playbook.get("failure_count") or 0) > 0:
        return None
    return int(top)
