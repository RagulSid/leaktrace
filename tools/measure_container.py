"""Measure the single-image container: memory at idle and during a full S1 run, and the time for one decision.

  python tools/measure_container.py --base http://127.0.0.1:8080 --container leaktrace-app

Everything goes over HTTP to the running container, as a visitor's browser would. Throwaway customers are created
inside the container with a random password (never printed) and deleted afterwards. Memory is `docker stats`
(the container's cgroup total) sampled about once a second, plus each process's resident memory from /proc.
"""

import argparse
import json
import os
import secrets
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scenario_generator.run import Session, _investigate, run_execution  # noqa: E402
from scenario_generator.scenarios import SCENARIOS  # noqa: E402


def mib(text: str) -> float:
    num, unit = float(text[:-3]), text[-3:]
    return num * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[unit] if unit in ("KiB", "MiB", "GiB") else float(text[:-1]) / 2**20


def container_mem(name: str) -> float:
    out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", name],
                         capture_output=True, text=True).stdout.strip()
    return round(mib(out.split(" / ")[0].strip()), 1)


def processes(name: str) -> list[dict]:
    script = ('for p in /proc/[0-9]*; do n=$(tr "\\0" " " < $p/cmdline 2>/dev/null | cut -c1-70); '
              'r=$(grep VmRSS $p/status 2>/dev/null | tr -s " " | cut -d" " -f2); '
              '[ -n "$r" ] && echo "$r|$n"; done')
    out = subprocess.run(["docker", "exec", name, "bash", "-c", script], capture_output=True, text=True).stdout
    rows = [line.split("|", 1) for line in out.splitlines() if "|" in line]
    return sorted(({"rss_mib": round(int(r) / 1024, 1), "cmd": c.strip()} for r, c in rows), key=lambda x: -x["rss_mib"])


class Sampler:
    def __init__(self, name: str):
        self.name, self.samples, self.stop = name, [], threading.Event()
        self.t = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.stop.is_set():
            self.samples.append(container_mem(self.name))

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.t.join()


def in_container(name: str, code: str, pw: str) -> None:
    subprocess.run(["docker", "exec", "-e", "MEASURE_PW=" + pw, name, "python", "-c", code], check=True,
                   capture_output=True, text=True)


def fresh(name: str, tenant: str, pw: str) -> None:
    in_container(name, f"import os; from app.cli import bootstrap; bootstrap({tenant!r}, password=os.environ['MEASURE_PW'])", pw)


def drop(name: str, tenant: str) -> None:
    subprocess.run(["docker", "exec", name, "python", "-c",
                    f"from app.graph.client import TenantGraph; TenantGraph({tenant!r}).delete()"], capture_output=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True)
    p.add_argument("--container", required=True)
    p.add_argument("--idle-s", type=int, default=30)
    p.add_argument("--decisions", type=int, default=3)
    a = p.parse_args(argv)
    out = {"base": a.base, "container": a.container, "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    with Sampler(a.container) as s:
        time.sleep(a.idle_s)
    out["idle_mib"] = {"min": min(s.samples), "max": max(s.samples), "samples": len(s.samples)}
    out["idle_processes"] = processes(a.container)

    times = []
    for i in range(a.decisions):
        tenant, pw = f"t_measure_d{i}_{secrets.token_hex(3)}", secrets.token_urlsafe(16)
        fresh(a.container, tenant, pw)
        try:
            sess = Session(tenant, pw, base_url=a.base)
            inv = _investigate(sess, SCENARIOS["s1"](7 + i), investigate=False, import_pack=True)
            t0 = time.perf_counter()
            d = sess.post(f"/incidents/{inv['incident']}/investigate", "operator1")
            times.append(round((time.perf_counter() - t0) * 1000))
            out.setdefault("decisions", []).append({"kind": d.get("kind"), "authority_level": d.get("authority_level"),
                                                    "ms": times[-1]})
        finally:
            drop(a.container, tenant)
    out["decision_ms"] = {"median": statistics.median(times), "min": min(times), "max": max(times), "n": len(times)}

    # Full S1 runs (approve, three valve moves by the simulated crew, readings, check), seeds 1 to 5. Memory is sampled
    # inside the container every 0.1 s from the cgroup (memory.current: everything the container holds, page cache
    # included, so it reads higher than `docker stats`).
    sampler = ("rm -f /tmp/peak; touch /tmp/sampling; m=0; while [ -f /tmp/sampling ]; do "
               "c=$(cat /sys/fs/cgroup/memory.current); if [ $c -gt $m ]; then m=$c; echo $m > /tmp/peak; fi; sleep 0.1; done")
    subprocess.run(["docker", "exec", "-d", a.container, "bash", "-c", sampler], check=True)
    runs, t_all = [], time.perf_counter()
    try:
        for seed in range(1, 6):
            tenant, pw = f"t_measure_s1_{seed}_{secrets.token_hex(3)}", secrets.token_urlsafe(16)
            fresh(a.container, tenant, pw)
            try:
                t0 = time.perf_counter()
                r = run_execution("s1", "happy", tenant, seed, base_url=a.base, password=pw, import_pack=True)
                runs.append({"seed": seed, "seconds": round(time.perf_counter() - t0, 2),
                             "final_status": (r.get("final") or {}).get("status")})
            finally:
                drop(a.container, tenant)
        out["s1_processes_at_end"] = processes(a.container)
    finally:
        subprocess.run(["docker", "exec", a.container, "rm", "-f", "/tmp/sampling"], capture_output=True)
        time.sleep(0.3)
    peak = subprocess.run(["docker", "exec", a.container, "cat", "/tmp/peak"], capture_output=True, text=True).stdout.strip()
    since_start = subprocess.run(["docker", "exec", a.container, "cat", "/sys/fs/cgroup/memory.peak"],
                                 capture_output=True, text=True).stdout.strip()
    out["s1_runs"] = runs
    out["s1_total_seconds"] = round(time.perf_counter() - t_all, 1)
    out["s1_peak_mib_cgroup"] = round(int(peak) / 2**20, 1) if peak else None
    out["peak_since_container_start_mib_cgroup"] = round(int(since_start) / 2**20, 1) if since_start else None
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
