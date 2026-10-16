"""Evidence confidence: a fixed, documented formula over counts read from the graph.

Four independent kinds of sign can point at a pipe section:
  1. leak alarm      a leak sensor on the section is in ALARM (+0.35); if none, an alarm elsewhere in
                     the same zone counts as a weaker "nearby" alarm (+0.10)
  2. pressure        a pressure sensor downstream of the section (open links) shows an ANOMALY (+0.20)
  3. flow imbalance  the smallest metered region containing the section loses more than the
                     tolerance: inflow - outflow > max(2, 5% of inflow) (+0.25)
  4. reports         at least one report about the section or its zone (+0.10), a second independent
                     reporter (+0.10 more)

Contradiction: that same smallest metered region is complete and balanced (-0.30).
Missing readings are "not available": they never count as proof and never as a contradiction.

Score = sum, clamped to [0, 1]. If fewer than two kinds are present the score is capped at 0.40, so a
single alarm, a single anomaly or a single report is never enough to act on.
"""

from dataclasses import dataclass, field

from app import config

W_LEAK_ALARM = 0.35
W_NEARBY_ALARM = 0.10
W_PRESSURE = 0.20
W_IMBALANCE = 0.25
W_REPORT = 0.10
W_SECOND_REPORTER = 0.10
CONTRADICTION_PENALTY = config.CONTRADICTION_PENALTY
SINGLE_KIND_CAP = config.SINGLE_KIND_CAP
KINDS_TOTAL = 4


def tolerance(inflow: float) -> float:
    return max(config.BALANCE_TOLERANCE_ABS, config.BALANCE_TOLERANCE_FRAC * abs(inflow))


@dataclass
class Balance:
    status: str  # "imbalanced" | "balanced" | "unknown"
    meter: str | None = None
    inflow: float | None = None
    outflow: float | None = None
    unaccounted: float | None = None
    out_meters: list[str] = field(default_factory=list)


def balance_view(regions: list[dict]) -> Balance:
    """Pick the smallest complete metered region (fewest outflow meters, all values present).
    `regions` are rows of flow_balance_for_segment."""
    complete = []
    for r in regions:
        outs = [o for o in r["outs"] if o.get("id") is not None]
        if not outs or r["inflow"] is None or any(o.get("value") is None for o in outs):
            continue
        complete.append((len(outs), r["meter"], r, outs))
    if not complete:
        return Balance("unknown")
    _, _, r, outs = min(complete, key=lambda t: (t[0], t[1]))
    inflow = float(r["inflow"])
    outflow = float(sum(o["value"] for o in outs))
    unaccounted = round(inflow - outflow, 3)
    status = "imbalanced" if unaccounted > tolerance(inflow) else "balanced"
    return Balance(status, r["meter"], inflow, outflow, unaccounted, sorted(o["id"] for o in outs))


@dataclass
class Signals:
    leak_alarms: list[str]
    zone_alarms: list[str]
    pressure_anomalies: list[str]
    reports: int
    reporters: int
    balance: Balance


@dataclass
class Confidence:
    score: float
    level: str  # "high" | "medium" | "low"
    kinds_present: list[str]
    kinds_total: int
    contradictions: list[str]
    parts: dict[str, float]

    @property
    def signs_agree(self) -> int:
        return len(self.kinds_present)


def level_for(score: float) -> str:
    return "high" if score >= config.CONFIDENCE_HIGH else "medium" if score >= config.CONFIDENCE_MEDIUM else "low"


def assess(s: Signals) -> Confidence:
    parts: dict[str, float] = {}
    kinds: list[str] = []
    if s.leak_alarms:
        parts["leak_alarm"] = W_LEAK_ALARM
        kinds.append("leak_alarm")
    elif s.zone_alarms:
        parts["leak_alarm_nearby"] = W_NEARBY_ALARM
        kinds.append("leak_alarm")
    if s.pressure_anomalies:
        parts["pressure"] = W_PRESSURE
        kinds.append("pressure")
    if s.balance.status == "imbalanced":
        parts["flow_imbalance"] = W_IMBALANCE
        kinds.append("flow_imbalance")
    if s.reports >= 1:
        parts["report"] = W_REPORT
        kinds.append("reports")
        if s.reporters >= 2:
            parts["second_reporter"] = W_SECOND_REPORTER
    contradictions = []
    if s.balance.status == "balanced":
        parts["balanced_region"] = -CONTRADICTION_PENALTY
        contradictions.append(f"flow balanced at {s.balance.meter}")
    score = max(0.0, min(1.0, sum(parts.values())))
    if len(kinds) < 2:
        score = min(score, SINGLE_KIND_CAP)
    score = round(score, 3)
    return Confidence(score, level_for(score), kinds, KINDS_TOTAL, contradictions, parts)
