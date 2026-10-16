"""Run the helpers for one customer until no step is open.

  python -m app.agents.worker --tenant demo [--chooser auto|llm|rules] [--max-steps 200]

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
    p.add_argument("--chooser", default=None, choices=["auto", "llm", "rules"])
    p.add_argument("--max-steps", type=int, default=200)
    a = p.parse_args(argv)
    try:
        chooser = choosers.default(a.chooser)
        done = runtime.drain(TenantGraph(a.tenant), chooser, a.max_steps)
    except GraphUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"pid": os.getpid(), "chooser": chooser.name, "steps": [asdict(d) for d in done]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
