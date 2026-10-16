"""Decision lifecycle: the states a committed plan moves through, and the only legal moves between them.

  proposed  --approve-->            approved   (L3: a person other than the requester; L2: auto mode)
  proposed | approved --reject-->   rejected
  proposed | approved --newer decision or stale-->  superseded
  approved  --approval expired-->   proposed
  approved  --execute-->            executing  (only after the stale-decision guard passes)
  executing --last move done-->     verifying
  executing --a move fails, or a worker is lost for good-->  failed
  verifying --every check passes--> verified
  verifying --a check fails, or no fresh readings in time-->  failed
  failed | verified --rollback / undo-->  rolling_back
  rolling_back --last undo step-->  rolled_back
  rolling_back --an undo step fails-->  rollback_failed  (people must check the valves)

Decisions that are not plans (request_evidence, escalate) are 'recorded' and never move.
Every transition is applied in the graph as one conditional write together with its audit record.
"""

ALLOWED = frozenset({
    ("proposed", "approved"),
    ("proposed", "rejected"),
    ("proposed", "superseded"),
    ("approved", "proposed"),
    ("approved", "rejected"),
    ("approved", "superseded"),
    ("approved", "executing"),
    ("executing", "verifying"),
    ("executing", "failed"),
    ("verifying", "verified"),
    ("verifying", "failed"),
    ("failed", "rolling_back"),
    ("verified", "rolling_back"),
    ("rolling_back", "rolled_back"),
    ("rolling_back", "rollback_failed"),
})

STATES = frozenset({s for pair in ALLOWED for s in pair} | {"recorded"})
OPEN = ("proposed", "approved")
IN_PROGRESS = ("executing", "verifying", "rolling_back")
REPLANNABLE = ("failed", "rolled_back", "rollback_failed", "rejected")


class IllegalTransition(ValueError):
    pass


def can(frm: str, to: str) -> bool:
    return (frm, to) in ALLOWED


def check(frm: str, to: str) -> None:
    if not can(frm, to):
        raise IllegalTransition(f"{frm} -> {to}")


def next_actions(status: str, authority_level: str | None) -> list[str]:
    """What a person can do next, for the status view (the engine still checks roles and states)."""
    if status == "proposed":
        if authority_level == "L4":
            return []  # people decide outside the system; never executed
        return ["execute"] if authority_level == "L2" else ["approve", "reject"]
    return {
        "approved": ["execute", "reject"],
        "verifying": ["verify"],
        "verified": ["rollback"],
        "failed": ["rollback", "replan"],
        "rolled_back": ["replan"],
        "rollback_failed": ["replan"],
        "rejected": ["replan"],
    }.get(status, [])
