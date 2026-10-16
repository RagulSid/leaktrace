"""Plan generation: which valve moves to consider for a suspected leak section.

Plans come only from graph results: the section's boundary valves (the first valves met walking out
along flow links) and the valves that are closed now (possible backup links). Every non-empty subset
of boundary valves to close, alone or with one backup valve opened, plus "do nothing" as plan 0.
"""

from dataclasses import dataclass, field
from itertools import combinations

from app import config



@dataclass(frozen=True)
class Plan:
    id: str
    close: tuple[str, ...] = ()
    open: tuple[str, ...] = ()
    l4_effects: tuple[str, ...] = field(default=())

    @property
    def kind(self) -> str:
        return "do_nothing" if not (self.close or self.open) else "valve_change"

    @property
    def ops(self) -> list[str]:
        return [f"close:{v}" for v in self.close] + [f"open:{v}" for v in self.open]

    @property
    def op_count(self) -> int:
        return len(self.close) + len(self.open)

    @property
    def valves(self) -> list[str]:
        return list(self.close) + list(self.open)

    @property
    def label(self) -> str:
        if self.kind == "do_nothing":
            return "do nothing"
        parts = []
        if self.close:
            parts.append("close " + " + ".join(self.close))
        if self.open:
            parts.append("open " + " + ".join(self.open))
        return ", ".join(parts)

    @property
    def rollback(self) -> list[str]:
        return [f"open:{v}" for v in self.close] + [f"close:{v}" for v in self.open]


def generate(key: str, boundary: list[str], backups: list[str]) -> list[Plan]:
    """`key` is a server-generated lowercase id used to build plan ids (and the what-if property names)."""
    boundary = sorted(set(boundary))[:config.MAX_BOUNDARY_VALVES]
    backups = [b for b in sorted(set(backups)) if b not in boundary][:config.MAX_BACKUP_VALVES]
    plans = [Plan(f"o_{key}_0")]
    n = 1
    for size in range(1, len(boundary) + 1):
        for close in combinations(boundary, size):
            for opened in [()] + [(b,) for b in backups]:
                plans.append(Plan(f"o_{key}_{n}", close, opened))
                n += 1
    return plans
