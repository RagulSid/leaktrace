"""Notification adapter (simulated). Nothing is sent anywhere: each notice is recorded as an Episode of the
problem, so the timeline shows who would have been told what."""

from app.graph.client import TenantGraph
from app.memory import episodic


def send(tg: TenantGraph, incident: str | None, *, to: list[str], message: str, code: str | None = None) -> str:
    """`code` names the kind of notice for screens (they show their own words); `message` is the log text."""
    return episodic.record(tg, incident=incident, actor="notifier", kind="notify", tool=None,
                           args={"to": to, "simulated": True, "code": code}, summary=message, ms=0.0, ok=True)
