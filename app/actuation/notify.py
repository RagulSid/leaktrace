"""Notification adapter (simulated). Nothing is sent anywhere: each notice is recorded as an Episode of the
problem, so the timeline shows who would have been told what."""

from app.graph.client import TenantGraph
from app.memory import episodic


def send(tg: TenantGraph, incident: str | None, *, to: list[str], message: str) -> str:
    return episodic.record(tg, incident=incident, actor="notifier", kind="notify", tool=None,
                           args={"to": to, "simulated": True}, summary=message, ms=0.0, ok=True)
