"""Conversation history: each person's turns with Ask LeakTrace, one conversation per person and problem, saved as
Conversation and Message nodes. Nothing is held in the server process, so a restart resumes where it was."""

import secrets

from app import clock
from app.graph.client import TenantGraph, rows

GENERAL = "general"


def conv_id(user: str, incident: str | None) -> str:
    return f"CONV-{user}-{incident or GENERAL}"


def save_turn(tg: TenantGraph, user: str, incident: str | None, question: str, result: dict) -> str:
    ts, cid = clock.now(), conv_id(user, incident)
    msgs = [
        {"id": "MSG-Q-" + secrets.token_hex(5), "role": "user", "text": question, "ts": ts, "seq": 0, "cites": [],
         "known": None, "phrased_by": None, "fallback": None, "offer": None},
        {"id": "MSG-A-" + secrets.token_hex(5), "role": "assistant", "text": result["answer"], "ts": ts, "seq": 1,
         "cites": [c["id"] for c in result["cites"]], "known": result["known"], "phrased_by": result["phrased_by"],
         "fallback": result.get("fallback"), "offer": result.get("offer")},
    ]
    tg.write("brain_conversation_append", {"user": user, "conv": cid, "incident": incident, "ts": ts, "messages": msgs})
    return cid


def history(tg: TenantGraph, user: str, incident: str | None) -> dict:
    """The saved turns, each answer's sources with what they are (read from the map again, so a source that
    has since gone shows as missing rather than with stale words)."""
    from app.brain.ask import kind_of

    cid = conv_id(user, incident)
    msgs = rows(tg.read("brain_conversation_get", {"conv": cid, "user": user}))
    ids = sorted({c for m in msgs for c in (m["cites"] or [])})
    found = {r["id"]: r for r in rows(tg.read("brain_nodes_exist", {"ids": ids}))} if ids else {}
    for m in msgs:
        m["cites"] = [{"id": c, "kind": kind_of(found[c]["labels"]) if c in found else "missing",
                       "title": found[c]["title"] if c in found else None} for c in (m["cites"] or [])]
    return {"conversation": cid, "messages": msgs}
