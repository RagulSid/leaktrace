"""Seeded, synthetic event streams for the data-centre pack. Everything is labelled source='synthetic'.

S1: a leak on the row A branch pipe (SEG-A1). Racks keep their nominal flow for now, so the row A
inflow meter reads high by the leak amount; the leak sensor on SEG-A1 alarms; pressure at manifold A
drops; a staff member reports water under rack A1.

S5: a low-risk leak on the rack A2 feed (SEG-A3): its leak sensor alarms, the row A inflow meter reads high,
a staff member reports water near rack A2. Rack A2 is not critical, so the plan can be handled automatically.
"""

import random

T0 = 1_760_000_000.0  # scenario clock start (epoch seconds)
NOMINAL = {"FM-RA1": 20.0, "FM-RA2": 15.0, "FM-RB1": 20.0, "FM-RB2": 15.0}


def _meters(rng: random.Random, leak_a: float) -> dict[str, float]:
    def noise() -> float:
        return round(rng.uniform(-0.4, 0.4), 2)

    v = {k: round(x + noise(), 2) for k, x in NOMINAL.items()}
    v["FM-A-IN"] = round(v["FM-RA1"] + v["FM-RA2"] + leak_a + noise(), 2)
    v["FM-B-IN"] = round(v["FM-RB1"] + v["FM-RB2"] + noise(), 2)
    v["FM-01"] = round(v["FM-A-IN"] + v["FM-B-IN"] + noise(), 2)
    return v


def _batch(ts: float, meters: dict[str, float], sensors: dict[str, str]) -> list[dict]:
    return ([{"id": k, "ts": ts, "value": x} for k, x in sorted(meters.items())]
            + [{"id": k, "ts": ts, "state": s} for k, s in sorted(sensors.items())])


def s1(seed: int) -> dict:
    rng = random.Random(seed)
    leak = round(rng.uniform(8.0, 16.0), 2)
    normal = {"LS-A1": "OK", "LS-A3": "OK", "LS-B1": "OK", "PS-MA": "OK", "PS-MB": "OK"}
    return {
        "id": "S1", "seed": seed, "leak_flow": leak, "leak_segment": "SEG-A1",
        "steps": [
            {"kind": "readings", "readings": _batch(T0, _meters(rng, 0.0), normal)},
            {"kind": "readings", "readings": _batch(T0 + 60, _meters(rng, leak),
                                                    {**normal, "LS-A1": "ALARM", "PS-MA": "ANOMALY"})},
            {"kind": "report", "as": "staff1", "text": "Water dripping under Rack A1 in Row A, small puddle by the tiles.",
             "hazard": True},
        ],
    }


def s5(seed: int) -> dict:
    rng = random.Random(seed)
    leak = round(rng.uniform(8.0, 12.0), 2)
    normal = {"LS-A1": "OK", "LS-A3": "OK", "LS-B1": "OK", "PS-MA": "OK", "PS-MB": "OK"}
    return {
        "id": "S5", "seed": seed, "leak_flow": leak, "leak_segment": "SEG-A3",
        "steps": [
            {"kind": "readings", "readings": _batch(T0, _meters(rng, 0.0), normal)},
            {"kind": "readings", "readings": _batch(T0 + 60, _meters(rng, leak), {**normal, "LS-A3": "ALARM"})},
            {"kind": "report", "as": "staff1", "text": "Water on the floor near Rack A2.", "hazard": False},
        ],
    }


def s1_leak_update(seed: int, leak: float, ts: float) -> list[dict]:
    """A later S1 reading batch with a different leak flow (the graph changes after a plan was approved)."""
    rng = random.Random(seed + 1000)
    return _batch(ts, _meters(rng, leak), {"LS-A1": "ALARM", "LS-A3": "OK", "LS-B1": "OK", "PS-MA": "ANOMALY", "PS-MB": "OK"})


def s2_report_only(seed: int) -> dict:
    """Ambiguous: one report, no alarm, meters balanced."""
    rng = random.Random(seed)
    normal = {"LS-A1": "OK", "LS-A3": "OK", "LS-B1": "OK", "PS-MA": "OK", "PS-MB": "OK"}
    return {
        "id": "S2", "seed": seed,
        "steps": [
            {"kind": "readings", "readings": _batch(T0, _meters(rng, 0.0), normal)},
            {"kind": "report", "as": "staff1", "text": "Think I heard dripping somewhere in Row A.", "hazard": False},
        ],
    }


SCENARIOS = {"s1": s1, "s2": s2_report_only, "s5": s5}
