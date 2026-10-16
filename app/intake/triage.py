"""Intake helper (L1): attach new evidence to the open problem in the same zone, or open a new one."""

import time

from app import ids
from app.graph.client import TenantGraph, rows


def severity_for_zone(tg: TenantGraph, zone: str | None) -> str:
    if zone is None:
        return "low"
    max_crit = rows(tg.read("zone_max_criticality", {"zone": zone}))[0]["max_criticality"] or 0
    return "high" if max_crit >= 4 else "medium" if max_crit >= 2 else "low"


def incident_for(tg: TenantGraph, zones: list[str], involve: list[str], source: str) -> str:
    """Open problem in any of `zones`, else a new one. Links the zones and `involve` ids to it."""
    incident = None
    for z in zones:
        found = rows(tg.read("incident_open_in_zone", {"zone": z}))
        if found:
            incident = found[0]["id"]
            break
    if incident is None:
        incident = ids.incident_id()
        tg.write("incident_create", {
            "id": incident, "severity": severity_for_zone(tg, zones[0] if zones else None),
            "ts": time.time(), "source": source,
        })
    tg.write("incident_involve", {"incident": incident, "ids": sorted(set(zones) | set(involve))})
    return incident
