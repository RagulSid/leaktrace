"""Did the plan work? Fresh readings after the last valve move, checked against what the plan expected.

The expected result is written on the Execution when it starts, from the committed decision:
  leak_segment      the section the plan cuts off
  isolation_meters  inflow meters on that section
  critical          for each critical consumer: its outflow meters and the flow the plan's max-flow check gave it
  pressure_sensors  the pressure sensors that showed an anomaly when the decision was made

Checks (all must pass):
  fresh_readings    every reading used below arrived after the last move (server receipt time)
  leak_isolated     every isolation meter reads at most ISOLATION_MAX_FLOW; with no isolation meter on the
                    section, the balance check below decides (the result says which method was used)
  critical_supplied every critical consumer's meter reads at least expected - tolerance(expected), and > 0
  pressure_normal   every pressure sensor that showed an anomaly reads OK again
  balance_restored  the smallest complete metered region around the section is balanced:
                    inflow - outflow <= max(2, 5% of inflow), the same tolerance the confidence formula uses
A leak sensor is deliberately not a check: water already on the floor keeps it wet after the leak is cut off.
"""

from app import config
from app.domain.confidence import Balance, tolerance
from app.domain.constraints import Check

ISOLATION_MAX_FLOW = config.ISOLATION_MAX_FLOW  # what a closed-off section's inflow meter may still show (noise)


def instruments(expected: dict, balance: Balance) -> list[str]:
    ids = list(expected.get("isolation_meters") or [])
    for c in (expected.get("critical") or {}).values():
        ids += c.get("meters") or []
    ids += expected.get("pressure_sensors") or []
    if balance.meter:
        ids += [balance.meter, *balance.out_meters]
    return sorted(set(ids))


def evaluate(expected: dict, readings: dict[str, dict], balance: Balance, since: float) -> tuple[list[Check], list[str]]:
    """Returns the checks and the instruments whose reading is not fresh yet (empty when all are)."""
    needed = instruments(expected, balance)
    stale = [i for i in needed if (readings.get(i) or {}).get("received_at") is None
             or readings[i]["received_at"] < since]

    def value(i):
        return (readings.get(i) or {}).get("value")

    checks = [Check("fresh_readings", not stale, {"not_fresh": stale, "since": since})]

    balanced = balance.status == "balanced"
    iso = expected.get("isolation_meters") or []
    if iso:
        vals = {m: value(m) for m in iso}
        checks.append(Check("leak_isolated", all(v is not None and v <= ISOLATION_MAX_FLOW for v in vals.values()),
                            {"method": "isolation_meters", "values": vals, "max_allowed": ISOLATION_MAX_FLOW}))
    else:
        checks.append(Check("leak_isolated", balanced, {"method": "balance", "balance": balance.status}))

    crit = {}
    ok = True
    for cid, c in sorted((expected.get("critical") or {}).items()):
        exp = float(c["expected"])
        floor = round(exp - tolerance(exp), 3)
        vals = {m: value(m) for m in c.get("meters") or []}
        good = bool(vals) and all(v is not None and v > 0 and v >= floor for v in vals.values())
        ok = ok and good
        crit[cid] = {"meters": vals, "expected": exp, "min_allowed": floor, "passed": good}
    checks.append(Check("critical_supplied", ok, {"consumers": crit}))

    ps = {s: (readings.get(s) or {}).get("state") for s in expected.get("pressure_sensors") or []}
    checks.append(Check("pressure_normal", all(v == "OK" for v in ps.values()), {"sensors": ps}))

    checks.append(Check("balance_restored", balanced, {
        "status": balance.status, "meter": balance.meter, "inflow": balance.inflow, "outflow": balance.outflow,
        "unaccounted": balance.unaccounted,
        "tolerance": tolerance(balance.inflow) if balance.inflow is not None else None,
    }))
    return checks, stale
