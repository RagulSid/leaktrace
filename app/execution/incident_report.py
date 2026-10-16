"""The incident report: facts read from the graph, plus prose.

The facts are exactly what incident_facts.cypher returns. The prose is written from those facts only: by the
language model when one is configured (the Record keeper passes its writer), otherwise by the fixed template
below. `prose_by` says which, so nobody mistakes a template for a model's summary.
"""

import json

from app import clock, ids
from app.graph.client import TenantGraph, rows

HELPER_KINDS = ["triage", "investigate", "plan", "dispatch", "verify", "record"]


def facts(tg: TenantGraph, incident: str) -> dict:
    out = rows(tg.read("incident_facts", {"id": incident, "kinds": HELPER_KINDS}))
    if not out:
        raise LookupError(incident)
    f = out[0]
    for k in ("decisions", "actions", "verifications", "work_orders", "handoffs", "facts"):
        f[k] = sorted([x for x in f[k] if any(v is not None for v in x.values())],
                      key=lambda x: (x.get("ts") or 0, json.dumps(x, sort_keys=True, default=str)))
    return f


def template_prose(f: dict) -> str:
    lines = [f"Problem {f['id']} in {', '.join(f['zones']) or 'an unknown zone'} "
             f"({f['severity']} severity) is {f['status']}."]
    if f["reports"]:
        lines.append(f"{len(f['reports'])} report(s) were received.")
    for d in f["decisions"]:
        lines.append(f"Decision {d['id']}: {d['summary']}; status {d['status']}.")
    if f["actions"]:
        moves = ", ".join(f"{a['to_state']} {a['valve']}" for a in f["actions"])
        lines.append(f"Valve changes made: {moves}.")
    for v in f["verifications"]:
        lines.append(f"Check of {v['decision']}: " + ("passed." if v["passed"] else
                                                     f"failed ({', '.join(v['failed_checks'])})."))
    if f["facts"]:
        lines.append("Learned: " + "; ".join(x["statement"] for x in f["facts"]) + ".")
    open_jobs = [w for w in f["work_orders"] if w["status"] != "done"]
    if f["work_orders"]:
        lines.append(f"{len(f['work_orders'])} job(s), {len(open_jobs)} still open.")
    if f["handoffs"]:
        lines.append("Helper steps: " + " -> ".join(h["kind"] for h in f["handoffs"]) + ".")
    lines.append("All data is practice data; no real equipment was moved.")
    return " ".join(lines)


def write(tg: TenantGraph, incident: str, actor: str, writer=None) -> dict:
    """`writer(facts) -> str` writes prose from the facts (a language model); without one the template is used."""
    f = facts(tg, incident)
    prose, by = (writer(f), "llm") if writer else (template_prose(f), "template")
    rid = "IR-" + ids.task_id()[4:]
    tg.write("incident_report_write", {"incident": incident, "id": rid, "ts": clock.now(),
                                       "facts": json.dumps(f, sort_keys=True, default=str), "prose": prose,
                                       "prose_by": by, "actor": actor})
    return {"id": rid, "incident": incident, "facts": f, "prose": prose, "prose_by": by}


def latest(tg: TenantGraph, incident: str) -> dict | None:
    out = rows(tg.read("incident_report_get", {"incident": incident}))
    if not out:
        return None
    r = out[0]
    return {"id": r["id"], "ts": r["ts"], "facts": json.loads(r["facts_json"]), "prose": r["prose"],
            "prose_by": r["prose_by"], "written_by": r["written_by"]}
