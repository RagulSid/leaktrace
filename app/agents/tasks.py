"""Task protocol: helpers coordinate only through Task nodes in the graph.

A claim is one conditional write (only an open task can be claimed), with a lease. When a lease runs
out, release_expired() puts the task back to open so another worker can pick it up.
"""

import json
import time

from app import ids
from app.graph.client import TenantGraph, rows


def create(tg: TenantGraph, *, incident: str, kind: str, payload: dict, actor: str, source: str = "system") -> str:
    tid = ids.task_id()
    tg.write("task_create_for", {
        "id": tid, "incident": incident, "kind": kind, "payload": json.dumps(payload, sort_keys=True),
        "ts": time.time(), "actor": actor, "source": source,
    })
    return tid


def claim(tg: TenantGraph, task: str, agent: str, lease_s: float, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return bool(tg.write("task_claim", {"id": task, "agent": agent, "until": now + lease_s}).result_set)


def release_expired(tg: TenantGraph, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    return rows(tg.write("task_release_expired", {"now": now}))[0]["ids"]


def status(tg: TenantGraph, task_ids: list[str]) -> list[dict]:
    return rows(tg.read("task_status", {"ids": task_ids}))
