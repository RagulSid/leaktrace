"""Procedural memory: a Playbook is a plan that worked before on the same pipe section.

Key = section + the plan's valve operations. The Record keeper counts each finished decision once: verified
adds a success, a failed or undone plan adds a failure. Counts drive earned autonomy (app/domain/authority.py).
"""

import hashlib

from app import clock
from app.graph.client import TenantGraph, rows


def key(segment: str, ops: list[str]) -> str:
    return f"{segment}|{'+'.join(sorted(ops))}"


def get(tg: TenantGraph, k: str) -> dict | None:
    out = rows(tg.read("playbook_get", {"key": k}))
    return out[0]["playbook"] if out else None


def record_outcome(tg: TenantGraph, decision: str, segment: str, ops: list[str], verified: bool) -> dict:
    k = key(segment, ops)
    out = rows(tg.write("playbook_record", {
        "decision": decision, "key": k, "id": "PB-" + hashlib.sha256(k.encode()).hexdigest()[:8].upper(),
        "name": f"{' + '.join(ops)} on {segment}", "segment": segment, "steps": list(ops),
        "s": 1 if verified else 0, "f": 0 if verified else 1, "outcome": "verified" if verified else "failed",
        "ts": clock.now(),
    }))
    return out[0]
