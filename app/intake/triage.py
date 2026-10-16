"""Intake helper (L1): attach new evidence to the open problem in the same zone, or open a new one."""

import json
import time

from app import config, ids
from app.graph.client import TenantGraph, rows


def severity_for_zone(tg: TenantGraph, zone: str | None) -> str:
    if zone is None:
        return "low"
    max_crit = rows(tg.read("zone_max_criticality", {"zone": zone}))[0]["max_criticality"] or 0
    return ("high" if max_crit >= config.SEVERITY_HIGH_CRITICALITY
            else "medium" if max_crit >= config.SEVERITY_MEDIUM_CRITICALITY else "low")


def incident_for(tg: TenantGraph, zones: list[str], involve: list[str], source: str, create: bool = True) -> str | None:
    """Open problem in any of `zones`, else a new one (only if `create`). Links the zones and `involve` ids
    to it. A new problem gets a 'triage' step for the Intake helper."""
    incident = None
    for z in zones:
        found = rows(tg.read("incident_open_in_zone", {"zone": z}))
        if found:
            incident = found[0]["id"]
            break
    if incident is None:
        if not create:
            return None
        incident = ids.incident_id()
        tg.write("incident_create", {
            "id": incident, "severity": severity_for_zone(tg, zones[0] if zones else None),
            "ts": time.time(), "source": source,
        })
        if config.AUTO_TRIAGE:
            tg.write("agent_task_create", {"incident": incident, "id": ids.task_id(), "kind": "triage",
                                           "payload": json.dumps({"incident": incident}), "ts": time.time(),
                                           "actor": "intake_system"})
    tg.write("incident_involve", {"incident": incident, "ids": sorted(set(zones) | set(involve))})
    return incident
