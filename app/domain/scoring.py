"""Ranking plans after the hard constraints (BUILD_PROMPT §10).

Plans that pass every check come first, ordered by criticality-weighted disruption, then by how many
valve moves they need. Plans that fail come after, ordered by how many checks they fail. The agent
commits to the first passing plan, with the second passing plan as fallback.
"""

from app.domain.constraints import PlanResult


def rank(results: list[PlanResult]) -> list[PlanResult]:
    def key(r: PlanResult):
        if r.passed:
            return (0, r.disruption, r.plan.op_count, 0, r.plan.id)
        return (1, len(r.failed_checks), r.disruption, r.plan.op_count, r.plan.id)

    return sorted(results, key=key)


def choose(ranked: list[PlanResult]) -> tuple[PlanResult | None, PlanResult | None]:
    passing = [r for r in ranked if r.passed]
    return (passing[0] if passing else None, passing[1] if len(passing) > 1 else None)
