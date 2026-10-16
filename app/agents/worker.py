"""Run the helpers for one customer until no step is open.

  python -m app.agents.worker --tenant demo [--chooser auto|model|rules] [--max-steps 200] [--loop SECONDS]

With --loop the worker keeps running: every SECONDS it runs the helpers until no step is open. If FalkorDB is
unreachable it says so and tries again on the next round (a server process should not die with the database).

Each run is a fresh process: helpers keep nothing between runs except what is in the graph.
Exit codes: 0 done, 2 FalkorDB unreachable.
"""

import argparse
import json
import os
import sys
from dataclasses import asdict

from app.agents import choosers, runtime
from app.graph.client import GraphUnavailable, TenantGraph


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="leaktrace-helpers")
    p.add_argument("--tenant", required=True)
    p.add_argument("--chooser", default=None, choices=["auto", "model", "llm", "rules"])
    p.add_argument("--max-steps", type=int, default=200)
    p.add_argument("--loop", type=float, default=None, metavar="SECONDS")
    a = p.parse_args(argv)
    if a.loop:
        return _loop(a)
    try:
        chooser = choosers.default(a.chooser)
        done = runtime.drain(TenantGraph(a.tenant), chooser, a.max_steps)
    except GraphUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"pid": os.getpid(), "chooser": chooser.name, "model_calls": getattr(chooser, "calls", 0),
                      "fallbacks": getattr(chooser, "fallbacks", []), "steps": [asdict(d) for d in done]}))
    return 0


def _loop(a) -> int:
    import time

    while True:
        try:
            chooser = choosers.default(a.chooser)  # a fresh call cap for every round
            done = runtime.drain(TenantGraph(a.tenant), chooser, a.max_steps)
            if done:
                print(json.dumps({"chooser": chooser.name, "model_calls": getattr(chooser, "calls", 0),
                                  "steps": [f"{d.kind}:{d.status}" for d in done]}), flush=True)
        except GraphUnavailable as e:
            print(f"error: {e}", file=sys.stderr, flush=True)
        time.sleep(a.loop)


if __name__ == "__main__":
    sys.exit(main())
