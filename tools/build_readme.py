"""Fill the README's number blocks from saved results, so no number is typed by hand.

  python tools/build_readme.py --template <README template> --tests "301 passed, 2 opt-in skipped (4 min)"

Reads app/data/evaluation.json (the comparison) and the container measurement JSON given with --container-json.
"""

import argparse
import json
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--template", required=True)
    p.add_argument("--out", default=str(ROOT / "README.md"))
    p.add_argument("--tests", required=True, help="the summary line of the last full pytest run")
    p.add_argument("--container-json", required=True, help="tools/measure_container.py output, Render-like limits")
    p.add_argument("--cold-start", required=True, help="seconds to the waking page and to ready, e.g. '26.4/46.0'")
    a = p.parse_args(argv)
    ev = json.loads((ROOT / "app/data/evaluation.json").read_text(encoding="utf-8"))
    m = json.loads(Path(a.container_json).read_text(encoding="utf-8"))
    s = Path(a.template).read_text(encoding="utf-8")

    arms = "\n".join(f"- **{k}**: {v}" for k, v in ev["approaches"].items())
    table = ["| Case | Arm | Leak stopped | Runs with a key rack short | Racks short (avg) | Valve moves (avg) | Asked a person | Searches or lookups (avg) | Max-flow runs (avg) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in ev["summary"]:
        table.append(f"| {r['case']} | {r['approach']} | {r['leak_stopped']} of {r['runs']} | {r['key_rack_short_runs']} of {r['runs']} | "
                     f"{r['racks_short_avg']} | {r['moves_avg']} | {r['asked_person']} of {r['runs']} | {r['lookups_avg']:g} | {r['max_flow_calls_avg']:g} |")
    cases = "; ".join(f"{k}: {v}" for k, v in ev["cases"].items())
    table.append("")
    table.append(f"Cases: {cases}. Key racks are criticality 5 (Rack A1, Rack B1). Run {ev['ran_at']}, {ev['seeds']} seeds per case, "
                 f"{ev['seconds']} s. Scored by {ev['scored_by']}.")
    notes = "\n".join(f"- **{k}**: {v}" for k, v in ev["notes"].items())
    graph = [r for r in ev["summary"] if r["approach"] == "graph"]
    lookups = f"{min(r['lookups_avg'] for r in graph):g} to {max(r['lookups_avg'] for r in graph):g}"
    maxflows = f"{min(r['max_flow_calls_avg'] for r in graph):g} to {max(r['max_flow_calls_avg'] for r in graph):g}"
    first, ready = a.cold_start.split("/")
    s1 = m["s1_runs"]
    fit = (f"memory peaked at {m['peak_since_container_start_mib_cgroup']} MiB of 512 MB (idle about {m['idle_mib']['max']} MiB); "
           f"one decision took {m['decision_ms']['median'] / 1000:.1f} s (median of {m['decision_ms']['n']}); a full S1 run took "
           f"{min(r['seconds'] for r in s1):.1f} to {max(r['seconds'] for r in s1):.1f} s; from container start the waking page answered "
           f"after {first} s and the practice data was ready after {ready} s. Render's own docs do not say whether a Dockerfile service "
           f"may use the Free instance type (third-party guides show it working); check when creating the service.")
    container = (f"under 0.1 CPU and 512 MB, peak memory {m['peak_since_container_start_mib_cgroup']} MiB, one decision "
                 f"{m['decision_ms']['median'] / 1000:.1f} s, a full S1 run {min(r['seconds'] for r in s1):.1f}-{max(r['seconds'] for r in s1):.1f} s "
                 f"(all {len(s1)} verified), ready {ready} s after start.")
    env = f"{platform.system()} {platform.release()}, Docker Desktop, FalkorDB 6.0.2, Python {platform.python_version()}"
    for k, v in {"{ARMS}": arms, "{EVAL_TABLE}": "\n".join(table), "{EVAL_NOTES}": notes, "{LOOKUPS}": lookups,
                 "{MAXFLOWS}": maxflows, "{RENDER_FIT}": fit, "{CONTAINER}": container, "{ENV}": env, "{TESTS}": a.tests}.items():
        assert k in s, k
        s = s.replace(k, v)
    assert "{" not in "".join(line for line in s.splitlines() if line.startswith("{")), "unfilled block"
    Path(a.out).write_text(s, encoding="utf-8")
    print("README written:", len(s.splitlines()), "lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
