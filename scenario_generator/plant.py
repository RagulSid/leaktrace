"""Simulated plant for practice mode: the valve actuators and the flows that result. Synthetic only.

This stands in for the physical world, so it is deliberately independent of the app: its own copy of the
pack, its own valve states, and its own way of working out flows (water goes to the leak first, then to
racks in order of criticality, each through successive shortest augmenting paths). The app never sees this
code. It only sees what the simulated field crew reports over REST and the meter readings posted after the
moves, and verification compares those readings with what the app's plan expected.

Faults it can play:
  stuck    a valve that does not move when commanded (the worker reports it)
  passing  a valve that reports closed but still lets water through (only the readings show it)
Commands are deduplicated by idempotency key, like a real device gateway: a replayed command reports
the first result and never moves the valve again.
"""

import random
from collections import defaultdict, deque

EPS = 1e-9
SRC, LEAK = "__source__", "__leak__"


class Plant:
    def __init__(self, pack: dict, *, seed: int, leak_segment: str | None = None, leak_flow: float = 0.0,
                 stuck=(), passing=()):
        self.pack = pack
        self.rng = random.Random(10_000 + seed)
        self.nodes = {n["id"]: n for n in pack["nodes"]}
        self.valves = {i: n["props"]["state"] for i, n in self.nodes.items() if "Valve" in n["labels"]}
        self.leak_segment, self.leak_flow = leak_segment, float(leak_flow)
        self.stuck, self.passing = set(stuck), set(passing)
        self.applied: dict[str, dict] = {}
        self.moves: list[dict] = []  # physical valve movements, in order
        self.leaked = bool(leak_segment and leak_flow > 0)

    # ---------------------------------------------------------------- devices

    def command(self, key: str, valve: str, target: str) -> dict:
        if key in self.applied:
            return {**self.applied[key], "replayed": True}
        if valve in self.stuck:
            res = {"ok": False, "observed": self.valves[valve], "reason": "stuck"}
        else:
            self.valves[valve] = target
            self.moves.append({"key": key, "valve": valve, "target": target})
            res = {"ok": True, "observed": target}
        self.applied[key] = res
        return dict(res)

    # ---------------------------------------------------------------- physics

    def _open(self, valve: str | None) -> bool:
        return valve is None or self.valves.get(valve) == "open" or valve in self.passing

    def solve(self) -> dict:
        cap: dict[tuple, float] = defaultdict(float)
        adj: dict[str, set] = defaultdict(set)

        def arc(u, v, c):
            cap[(u, v)] += c
            adj[u].add(v)
            adj[v].add(u)

        for f in self.pack["flows"]:
            c = float(f["cap"]) if self._open(f.get("valve_id")) else 0.0
            arc(f["from"], f["to"], c)
            if f.get("two_way"):
                arc(f["to"], f["from"], c)
        for i, n in self.nodes.items():
            if "Source" in n["labels"]:
                arc(SRC, i, float(n["props"].get("supply_capacity", 1e9)))
        targets = []
        if self.leak_segment and self.leak_flow > 0:
            arc(self.leak_segment, LEAK, self.leak_flow)
            targets.append((LEAK, self.leak_flow))
        racks = sorted((i for i, n in self.nodes.items() if "Consumer" in n["labels"]),
                       key=lambda i: (-(self.nodes[i]["props"].get("criticality") or 0), i))
        for r in racks:
            arc(r, f"__sink_{r}", float(self.nodes[r]["props"]["required_flow"]))
            targets.append((f"__sink_{r}", float(self.nodes[r]["props"]["required_flow"])))
        terminals = {t for t, _ in targets}

        net: dict[tuple, float] = defaultdict(float)
        delivered = {}
        for t, demand in targets:
            got = 0.0
            while got < demand - EPS:
                prev = {SRC: None}
                q = deque([SRC])
                while q and t not in prev:
                    u = q.popleft()
                    for v in sorted(adj[u]):
                        if v not in prev and cap[(u, v)] > EPS and (v == t or v not in terminals):
                            prev[v] = u
                            q.append(v)
                if t not in prev:
                    break
                path, v = [], t
                while prev[v] is not None:
                    path.append((prev[v], v))
                    v = prev[v]
                push = min(min(cap[e] for e in path), demand - got)
                for u, v in path:
                    cap[(u, v)] -= push
                    cap[(v, u)] += push
                    net[(u, v)] += push
                    net[(v, u)] -= push
                got += push
            delivered[t] = round(got, 6)

        def inflow(node):
            return sum(max(0.0, net[(u, node)]) for u in adj[node] if not u.startswith("__"))

        downstream_of_leak = set()
        if delivered.get(LEAK, 0) > EPS:
            q = deque([self.leak_segment])
            while q:
                u = q.popleft()
                for v in adj[u]:
                    if not v.startswith("__") and net[(u, v)] > EPS and v not in downstream_of_leak:
                        downstream_of_leak.add(v)
                        q.append(v)
        return {"leak": delivered.get(LEAK, 0.0),
                "racks": {r: delivered[f"__sink_{r}"] for r in racks},
                "inflow": {i: round(inflow(i), 6) for i in self.nodes},
                "downstream_of_leak": downstream_of_leak}

    def readings(self, ts: float) -> list[dict]:
        """One batch for POST /readings: every meter and sensor, from the current valve states."""
        s = self.solve()
        links = self.pack["links"]
        measures = {ln["from"]: ln["to"] for ln in links if ln["type"] == "MEASURES"}
        monitors = {ln["from"]: ln["to"] for ln in links if ln["type"] == "MONITORS"}
        out = []
        for i in sorted(self.nodes):
            n = self.nodes[i]
            if "Meter" in n["labels"] and i in measures:
                v = s["inflow"][measures[i]] + self.rng.uniform(-0.4, 0.4)
                out.append({"id": i, "ts": ts, "value": round(max(0.0, v), 2)})
            elif "Sensor" in n["labels"]:
                watched = monitors.get(i)
                if n["props"]["kind"] == "leak":
                    state = "ALARM" if self.leaked and watched == self.leak_segment else "OK"
                else:  # pressure at a junction: a leak upstream of it, or nothing reaching it
                    fed = s["inflow"].get(watched, 0.0) > EPS
                    state = "ANOMALY" if (watched in s["downstream_of_leak"] or not fed) else "OK"
                out.append({"id": i, "ts": ts, "state": state})
        return out
