"""Reading intake (L0): sensor states and meter values.

A sensor that goes into ALARM or ANOMALY opens a problem in its zone, or joins the open one. A sensor that
was already in that state only joins an open problem: water still on the floor after a verified fix does
not reopen it. A new alarm after the sensor was reset opens a new problem.

Each reading updates the instrument's current state or value and appends a Reading node; history is
capped at READING_HISTORY per instrument.
"""

from app import clock, config, ids
from app.graph.client import TenantGraph, rows
from app.intake.triage import incident_for

READING_HISTORY = config.READING_HISTORY
SENSOR_STATES = {"OK", "ALARM", "ANOMALY"}
ALERT_STATES = {"ALARM", "ANOMALY"}


class BadReadings(ValueError):
    pass


def ingest_readings(tg: TenantGraph, readings: list[dict], source: str = "synthetic") -> dict:
    if not readings:
        raise BadReadings("no readings")
    wanted = sorted({r["id"] for r in readings})
    ctx = {r["id"]: r for r in rows(tg.read("instrument_context", {"ids": wanted}))}
    unknown = [i for i in wanted if i not in ctx]
    if unknown:
        raise BadReadings(f"unknown instruments: {unknown}")

    out_rows = []
    for r in readings:
        kind = ctx[r["id"]]["instrument"]
        state, value = r.get("state"), r.get("value")
        if kind == "sensor" and state not in SENSOR_STATES:
            raise BadReadings(f"{r['id']}: sensor state must be one of {sorted(SENSOR_STATES)}")
        if kind == "meter" and not isinstance(value, (int, float)):
            raise BadReadings(f"{r['id']}: meter reading needs a numeric value")
        if not isinstance(r.get("ts"), (int, float)):
            raise BadReadings(f"{r['id']}: ts (epoch seconds) is required")
        out_rows.append({
            "id": r["id"], "rid": ids.reading_id(), "ts": float(r["ts"]), "source": source,
            "state": state if kind == "sensor" else None,
            "value": float(value) if kind == "meter" else None,
        })
    tg.write("reading_apply", {"rows": out_rows, "received_at": clock.now()})
    tg.write("reading_trim", {"ids": wanted, "keep": READING_HISTORY})

    incidents: dict[str, str] = {}
    for r in out_rows:
        c = ctx[r["id"]]
        if c["instrument"] == "sensor" and r["state"] in ALERT_STATES:
            zones = [c["zone"]] if c["zone"] else []
            new_alarm = c["prev_state"] not in ALERT_STATES
            found = incident_for(tg, zones, [r["id"], *c["watches"]], source, create=new_alarm)
            if found:
                incidents[r["id"]] = found
            c["prev_state"] = r["state"]  # a second reading in the same batch is not a new alarm
    return {"applied": len(out_rows), "incidents": incidents}
