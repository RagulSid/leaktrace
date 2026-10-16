"""Actuator interface: how the engine asks for valves to move.

The engine never moves a valve itself. It turns a plan into ordered commands and an actuator carries
them out and reports back. Commands are absolute ("V-01 closed", never "toggle V-01") and each carries
an idempotency key, so a command that is retried can never move a valve twice.

FieldTaskActuator is the only actuator in this build. Each command becomes a Task node in the graph that
a field crew member (or a device gateway) claims with a lease and reports on over REST:
POST /tasks/claim, then POST /tasks/{id}/result. No real equipment is connected. In practice mode the
worker is the scenario simulator, which reaches the app only through those routes.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Move:
    valve: str
    target: str  # "open" | "closed"
    prior_state: str  # the valve state the graph shows before this command
    edge_ids: tuple[str, ...]  # flow links this valve controls
    edge_caps: tuple[float, ...]  # their cap_base once the command is done


class Actuator(Protocol):
    name: str
    simulated: bool

    def commands(self, execution_id: str, phase: str, moves: list[Move]) -> list[dict]:
        """Task rows to dispatch, in order. Only the first is open; the rest wait for the one before."""

    def outcome(self, target: str, reported: str, observed: str | None, reason: str | None) -> tuple[str, str | None]:
        """Normalise a worker's report into ('done', None) or ('failed', reason)."""


class FieldTaskActuator:
    name = "field_tasks"
    simulated = True

    def commands(self, execution_id: str, phase: str, moves: list[Move]) -> list[dict]:
        from app import ids

        return [{
            "id": ids.task_id(), "phase": phase, "seq": seq, "status": "open" if seq == 1 else "pending",
            "valve": m.valve, "target": m.target, "prior_state": m.prior_state,
            "edge_ids": list(m.edge_ids), "edge_caps": list(m.edge_caps),
            "idem_key": f"{execution_id}:{phase}:{seq}:{m.valve}:{m.target}",
        } for seq, m in enumerate(moves, 1)]

    def outcome(self, target: str, reported: str, observed: str | None, reason: str | None) -> tuple[str, str | None]:
        # A move counts as done only if the worker saw the valve in the target state.
        if reported == "done":
            return ("done", None) if observed == target else ("failed", "wrong_state")
        return "failed", (reason or "error")


ACTUATOR: Actuator = FieldTaskActuator()


def make_before_break(ops: list[str]) -> list[tuple[str, str]]:
    """Order a plan's valve operations: opening valves first (backup supply comes on), then closing them,
    each group in plan order. With S1 that keeps rack A1 fed throughout: open V-09, close V-01, close V-07.
    Returns (valve, target state) pairs."""
    parsed = []
    for op in ops:
        verb, _, valve = op.partition(":")
        if verb not in ("open", "close") or not valve:
            raise ValueError(f"not a valve operation: {op!r}")
        parsed.append((verb, valve))
    opens = [(v, "open") for verb, v in parsed if verb == "open"]
    closes = [(v, "closed") for verb, v in parsed if verb == "close"]
    return opens + closes
