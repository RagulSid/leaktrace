import os

# Tests run against a local FalkorDB: a short connect timeout makes the FalkorDB-down tests fail fast
# (on Windows a refused connection otherwise takes about 2 s per attempt). Subprocesses inherit it.
os.environ.setdefault("FALKORDB_CONNECT_TIMEOUT_S", "0.5")
# Tests never call a real language model, even when .env holds a key: an empty value set here wins over .env
# (python-dotenv does not override variables that already exist). Model behaviour is tested with fakes.
if os.environ.get("LEAKTRACE_TEST_REAL_MODEL") != "1":
    os.environ["LLM_API_KEY"] = ""

import uuid
from pathlib import Path

import pytest

from app.graph.client import TenantGraph
from app.graph.importer import import_pack, load_pack
from app.graph.schema import ensure_schema

ROOT = Path(__file__).resolve().parents[1]
DATACENTER_PACK = ROOT / "packs" / "datacenter" / "topology.json"


def fresh_tenant() -> str:
    return "t_" + uuid.uuid4().hex[:12]


@pytest.fixture
def make_graph():
    """Factory for throwaway tenant graphs, deleted after the test."""
    made = []

    def _make(pack: dict | None = None) -> TenantGraph:
        tg = TenantGraph(fresh_tenant())
        made.append(tg)
        ensure_schema(tg)
        if pack is not None:
            import_pack(tg, pack)
        return tg

    yield _make
    for tg in made:
        try:
            tg.delete()
        except Exception:
            pass


@pytest.fixture
def dc(make_graph) -> TenantGraph:
    """A fresh tenant graph loaded with the synthetic data-centre pack."""
    return make_graph(load_pack(DATACENTER_PACK))


# ---------------------------------------------------------------- saved check results for the How it works page
# The page shows these as "the checks we ran". They are written by the test run itself, never by hand: a check
# is updated only when its test ran in this session.
CHECKS = {
    "kill_switch": "tests/test_kill_switch.py::test_api_fails_loudly_without_falkordb",
    "tenant_isolation": "tests/test_auth_tenancy.py::test_token_for_a_cannot_see_b",
    "restart_recall": "tests/test_restart_recall.py::test_stuck_valve_is_recalled_after_restart_and_changes_the_plan",
    "undo_works": "tests/test_execution_scenarios.py::test_v07_stuck_mid_plan_undo_restores_the_exact_prior_state",
    "read_only_rejects_writes": "tests/test_graph_foundation.py::test_ro_query_rejects_writes",
    "claim_race": "tests/test_vector_and_claim.py::test_claim_race_exactly_one_winner_per_task",
    "how_it_works_honest": "tests/test_how_it_works.py::test_numbers_are_live_and_change_with_the_data",
}
_outcomes: dict[str, str] = {}


def pytest_runtest_logreport(report):
    nodeid = report.nodeid.replace("\\", "/")
    for key, target in CHECKS.items():
        if nodeid == target:
            if report.when == "call" or report.failed:
                if report.skipped:
                    continue
                _outcomes[key] = "fail" if report.failed else _outcomes.get(key, "pass")


def pytest_sessionfinish(session, exitstatus):
    if not _outcomes:
        return
    import datetime
    import json
    import platform
    import sys

    path = ROOT / "app" / "data" / "checks.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"checks": {}}
    when = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    env = f"{platform.system()} {platform.release()}, Python {sys.version.split()[0]}, FalkorDB image pinned in docker-compose.yml"
    for key, outcome in _outcomes.items():
        data["checks"][key] = {"result": outcome, "when": when, "environment": env, "test": CHECKS[key]}
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
