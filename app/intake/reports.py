"""Report intake (L0/L1): resolve free text against names and ids in the graph, link, and triage.

Resolution is deterministic: a report mentions a thing only if its id or registered name appears in the
text as a whole word (longest match wins), or if the reporter gives an asset code (QR). Text that matches
nothing is still stored; it just links to nothing. A model may later propose candidates, but they are
always resolved against the graph the same way.
"""

import re
import time

from app import ids
from app.graph.client import TenantGraph, rows
from app.intake.triage import incident_for


class UnknownAsset(ValueError):
    pass


def resolve(catalog: list[dict], text: str) -> list[str]:
    terms = []
    for e in catalog:
        for t in {e["id"], e.get("name")}:
            if t:
                terms.append((t, e["id"]))
    terms.sort(key=lambda t: -len(t[0]))
    taken: list[tuple[int, int]] = []
    found: list[str] = []
    for term, eid in terms:
        for m in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.IGNORECASE):
            if any(m.start() < b and a < m.end() for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            if eid not in found:
                found.append(eid)
    return found


def ingest_report(tg: TenantGraph, *, text: str, reporter: str, asset_code: str | None = None,
                  hazard: bool = False, source: str = "synthetic") -> dict:
    catalog = rows(tg.read("entity_catalog"))
    about = resolve(catalog, text)
    if asset_code:
        if asset_code not in {e["id"] for e in catalog}:
            raise UnknownAsset(asset_code)
        about = [asset_code] + [a for a in about if a != asset_code]
    zones = sorted({r["zone"] for r in rows(tg.read("entity_zones", {"ids": about})) if r["zone"]})

    rid, code = ids.report_id(), ids.report_code()
    tg.write("report_create", {
        "id": rid, "code": code, "text": text, "reporter": reporter, "ts": time.time(),
        "hazard": bool(hazard), "source": source,
    })
    incident = incident_for(tg, zones, about, source)
    tg.write("report_link", {"report": rid, "incident": incident, "about": about})
    return {"code": code, "report": rid, "incident": incident, "about": about, "zones": zones}


def report_status(tg: TenantGraph, code: str) -> dict | None:
    out = rows(tg.read("report_by_code", {"code": code}))
    return out[0] if out else None
