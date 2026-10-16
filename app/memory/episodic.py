"""Episodic memory: every tool call becomes an Episode node linked to its incident."""

import json

from app import clock, ids
from app.graph.client import TenantGraph, rows


def record(tg: TenantGraph, *, incident: str | None, actor: str, kind: str, tool: str | None,
           args: dict, summary: str, ms: float, ok: bool) -> str:
    eid = ids.episode_id()
    tg.write("episode_write", {
        "id": eid, "kind": kind, "ts": clock.next_ns(), "actor": actor, "tool": tool,
        "args_json": json.dumps(args, default=str, sort_keys=True)[:4000],
        "summary": summary[:500], "ms": round(ms, 2), "ok": ok, "incident": incident,
    })
    return eid


def for_incident(tg: TenantGraph, incident: str) -> list[dict]:
    """Every recorded step of a problem, oldest first. For helper steps, `chooser` is exactly what was recorded
    when the step ran ("rules" or a model name) and `fallback` why the rules stood in, if they did."""
    out = rows(tg.read("episodes_for_incident", {"incident": incident}))
    for e in out:
        args = json.loads(e.pop("args_json") or "{}")
        e["chooser"] = args.pop("chooser", None)
        e["fallback"] = args.pop("fallback", None)
        e["task"] = args.pop("task", None)
        e["args"] = args
    return out
