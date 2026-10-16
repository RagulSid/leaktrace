"""Graph fingerprint for the stale-decision guard.

A decision stores the snapshot of the graph it was computed on (world_snapshot.cypher). Before anything
is executed the engine reads the snapshot again and lists the material changes:

  structure  any change in a valve's state, lock or reversibility; a consumer's criticality or required
             flow; a workload's criticality or migratability; a link capacity; the active facts; the
             policy limits; a sensor state. (Pausing auto mode is not part of it: it only changes who must
             approve, and the engine handles it separately.)
  meters     a value that moved by more than the balance tolerance, max(2, 5% of the earlier value), or
             a meter that had no value before and has one now.

The fingerprint is a SHA-256 of the structural part. It is stored on the decision, so the audit trail can
show which world a plan was approved for.
"""

import hashlib
import json

from app.domain.confidence import tolerance

STRUCTURAL = ("valves", "consumers", "workloads", "edges", "facts", "policies", "sensors")


def _keyed(rows: list) -> dict:
    return {str(r[0]): list(r[1:]) for r in rows or []}


def normalise(snapshot: dict) -> dict:
    return {k: dict(sorted(_keyed(snapshot.get(k)).items())) for k in (*STRUCTURAL, "meters")}


def fingerprint(snapshot: dict) -> str:
    n = normalise(snapshot)
    body = json.dumps({k: n[k] for k in STRUCTURAL}, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def material_changes(old: dict, new: dict) -> list[str]:
    a, b = normalise(old), normalise(new)
    out: list[str] = []
    for kind in STRUCTURAL:
        for key in sorted(set(a[kind]) | set(b[kind])):
            before, after = a[kind].get(key), b[kind].get(key)
            if before != after:
                out.append(f"{kind[:-1]} {key}: {before} -> {after}")
    for key in sorted(set(a["meters"]) | set(b["meters"])):
        before = (a["meters"].get(key) or [None])[0]
        after = (b["meters"].get(key) or [None])[0]
        if before is None and after is None:
            continue
        if before is None or after is None or abs(after - before) > tolerance(before):
            out.append(f"meter {key}: {before} -> {after}")
    return out
